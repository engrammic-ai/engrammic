"""Recovery routines for malformed pydantic-ai structured outputs.

When the LLM returns a tool-call dict that fails pydantic schema validation,
these helpers attempt deterministic remapping (enum-case fixups, list/scalar
coercion) before re-validating. As a last resort the raw string is re-parsed
via json_repair in case the underlying JSON wire format itself was malformed
(rare with tool-call APIs but observed with some Gemini failure modes).

The public entry point is ``patch_agent_output_validators``, which wraps the
``PluggableSchemaValidator`` instances on a pydantic-ai Agent's output toolset
in-place. It must be called after the Agent is constructed, before any run.

Re-entrancy guard
-----------------
pydantic installs ``PluggableSchemaValidator`` as a plugin that intercepts ALL
``validate_python`` / ``validate_json`` calls for a model type, including those
made by ``model_validate`` inside ``recover_output``.  Without a guard this
causes infinite recursion.  ``_in_recovery`` is a ``ContextVar`` that is set
before ``recover_output`` attempts validation; the patched validators detect it
and delegate straight to ``orig`` without attempting recovery again.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from pydantic import BaseModel, ValidationError

from context_service.config.logging import get_logger
from context_service.llm.base import robust_json_loads
from context_service.utils.json import JSONDecodeError

logger = get_logger(__name__)

# Re-entrancy guard: set while recover_output is executing so that recursive
# calls through the patched validator short-circuit without attempting recovery.
_in_recovery: ContextVar[bool] = ContextVar("_custodian_in_recovery", default=False)


# ---------------------------------------------------------------------------
# Recovery logic
# ---------------------------------------------------------------------------


def recover_output[M: BaseModel](
    raw: Any,
    output_type: type[M],
) -> M | None:
    """Attempt to recover a pydantic-ai output from a malformed payload.

    Returns the validated instance on success, or None if recovery fails.
    Sets ``_in_recovery`` before calling ``model_validate`` so that patched
    validators short-circuit and don't recurse back into this function.
    """
    token = _in_recovery.set(True)
    try:
        return _recover_inner(raw, output_type)
    finally:
        _in_recovery.reset(token)


def _recover_inner[M: BaseModel](raw: Any, output_type: type[M]) -> M | None:
    # Normalise: if raw is a string, parse it first
    if isinstance(raw, str):
        try:
            raw = robust_json_loads(raw)
        except (ValueError, JSONDecodeError) as exc:
            logger.debug(f"recover_output: robust_loads failed: {exc}")
            return None

    if not isinstance(raw, dict):
        return None

    # Strategy 1: direct model_validate (may succeed where pydantic-core fails)
    try:
        return output_type.model_validate(raw)
    except ValidationError:
        pass

    # Strategy 2: remap known mis-shapes then re-validate
    remapped = _remap_dict(raw)
    try:
        return output_type.model_validate(remapped)
    except ValidationError as exc:
        logger.debug(f"recover_output: dict-remap failed: {exc}")

    return None


def _remap_dict(d: dict[str, Any]) -> dict[str, Any]:
    """Apply known mis-shape repair rules to a candidate output dict.

    Rules are based on observed Gemini failure modes when producing structured
    tool-call outputs against strict pydantic schemas.

    Rule 1: enum-case fixup. Gemini returns uppercase/titlecase enum
    variants ("Low", "MEDIUM") when the schema requires lowercase.
    Guard: only apply to short strings unlikely to be free-form content.
    """
    out: dict[str, Any] = {}
    for key, value in d.items():
        if isinstance(value, str) and value != value.lower() and len(value) <= 32:
            out[key] = value.lower()
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Validator patching
# ---------------------------------------------------------------------------


def _make_recovering_validate_python(
    orig: Any,
    output_type: type[BaseModel],
    agent_label: str,
) -> Any:
    """Return a drop-in replacement for PluggableSchemaValidator.validate_python.

    On ValidationError, attempts recovery before re-raising.
    Short-circuits (delegates to orig) when called re-entrantly from inside
    recover_output to avoid infinite recursion.
    """

    def recovering_validate_python(
        data: Any,
        *,
        allow_partial: Any = "off",
        context: Any = None,
        **kwargs: Any,
    ) -> Any:
        if _in_recovery.get():
            return orig(data, allow_partial=allow_partial, context=context, **kwargs)
        try:
            return orig(data, allow_partial=allow_partial, context=context, **kwargs)
        except ValidationError as ve:
            recovered = recover_output(data, output_type)
            if recovered is not None:
                logger.info(
                    f"custodian.{agent_label}: recovered malformed output via output_recovery "
                    f"(validate_python)"
                )
                return recovered
            logger.warning(
                f"custodian.{agent_label}: validation failed; "
                f"raw_output_type={type(data).__name__}, "
                f"errors={ve.errors(include_url=False)[:3]}"
            )
            raise

    return recovering_validate_python


def _make_recovering_validate_json(
    orig: Any,
    output_type: type[BaseModel],
    agent_label: str,
) -> Any:
    """Return a drop-in replacement for PluggableSchemaValidator.validate_json.

    Short-circuits when called re-entrantly from inside recover_output.
    """

    def recovering_validate_json(
        data: str,
        *,
        allow_partial: Any = "off",
        context: Any = None,
        **kwargs: Any,
    ) -> Any:
        if _in_recovery.get():
            return orig(data, allow_partial=allow_partial, context=context, **kwargs)
        try:
            return orig(data, allow_partial=allow_partial, context=context, **kwargs)
        except ValidationError as ve:
            recovered = recover_output(data, output_type)
            if recovered is not None:
                logger.info(
                    f"custodian.{agent_label}: recovered malformed output via output_recovery "
                    f"(validate_json)"
                )
                return recovered
            logger.warning(
                f"custodian.{agent_label}: validation failed; "
                f"raw_output_type={type(data).__name__}, "
                f"errors={ve.errors(include_url=False)[:3]}"
            )
            raise

    return recovering_validate_json


def patch_agent_output_validators(
    agent: Any,
    output_type: type[BaseModel],
    label: str,
) -> None:
    """No-op: enum-case recovery migrated to model_validator(mode='before') on output types.

    Enum-case fixups (_remap_dict) are now applied deterministically in
    models.py before pydantic validates Literal constraints, which eliminates
    the need to monkey-patch pydantic-ai's private _output_toolset.processors.
    This function is kept as a no-op so call sites don't need to be updated.
    """
    # Previously mutated agent._output_toolset.processors[*].validator in-place.
    # Redundant now that custodian output models carry model_validator(mode='before').
    _ = agent, output_type, label
