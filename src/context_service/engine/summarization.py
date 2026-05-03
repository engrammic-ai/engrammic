"""LLM-based summarization for reasoning chains."""

from __future__ import annotations

from typing import Any, Protocol

import structlog

from context_service.config.settings import get_settings

logger = structlog.get_logger(__name__)


def _get_inline_threshold() -> int:
    """Get threshold at call time (not cached at import) for hot-reload support."""
    return get_settings().compaction_step_threshold


_SUMMARIZATION_PROMPT = """Summarize this reasoning chain concisely. Capture the key steps, conclusions, and final outcome. Be brief but preserve important details.

Reasoning steps:
{steps_text}

Summary:"""


class SummarizationClient(Protocol):
    """Protocol for LLM client used in summarization."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> tuple[str, Any]: ...


def _format_steps_for_prompt(steps: list[dict[str, Any]]) -> str:
    """Format steps for LLM prompt."""
    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))
    lines = []
    for s in sorted_steps:
        idx = s.get("step_index", "?")
        op = s.get("operation", "step")
        conclusion = s.get("conclusion", "")
        lines.append(f"[{idx}] {op}: {conclusion}")
    return "\n".join(lines)


def inline_summary(steps: list[dict[str, Any]]) -> str:
    """Inline all steps for short chains (public for fallback use)."""
    if not steps:
        return "(no steps)"
    sorted_steps = sorted(steps, key=lambda s: s.get("step_index", 0))
    lines = [
        f"[{s.get('step_index', i)}] {s.get('operation', 'step')}: {s.get('conclusion', '')}"
        for i, s in enumerate(sorted_steps)
    ]
    return "; ".join(lines)


async def summarize_reasoning_steps(
    steps: list[dict[str, Any]],
    llm_client: SummarizationClient | None = None,
) -> str:
    """Summarize reasoning steps, using LLM for long chains.

    For chains <= _INLINE_THRESHOLD steps, returns inline summary.
    For longer chains, calls LLM for semantic summarization.

    Args:
        steps: List of step dicts with step_index, operation, conclusion.
        llm_client: LLM client for summarization. If None and chain is long,
            raises ValueError.

    Returns:
        Summary string.

    Raises:
        ValueError: If chain is long but no LLM client provided.
    """
    if not steps:
        return "(no steps)"

    threshold = _get_inline_threshold()
    if len(steps) <= threshold:
        return inline_summary(steps)

    if llm_client is None:
        raise ValueError(f"LLM client required for chains > {threshold} steps")

    steps_text = _format_steps_for_prompt(steps)
    prompt = _SUMMARIZATION_PROMPT.format(steps_text=steps_text)

    logger.info("summarizing_chain", step_count=len(steps))
    text, _ = await llm_client.complete(
        [{"role": "user", "content": prompt}],
    )

    return text.strip()
