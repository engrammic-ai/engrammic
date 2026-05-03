"""Abstract base class for LLM providers."""

from __future__ import annotations

import abc
from typing import Any

from context_service.config.logging import get_logger
from context_service.utils.json import JSONDecodeError, loads

logger = get_logger(__name__)


class Usage:
    """Token usage from an LLM call."""

    __slots__ = ("model", "input_tokens", "output_tokens")

    def __init__(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        self.model = model
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    @classmethod
    def zero(cls, model: str) -> Usage:
        """Create a zero-usage instance."""
        return cls(model, 0, 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def truncate(text: str, max_len: int = 200) -> str:
    """Truncate text to max_len characters for safe logging (prevents PII leakage)."""
    return text[:max_len] if len(text) > max_len else text


def robust_json_loads(text: str) -> Any:
    """Parse JSON with automatic repair for malformed LLM output.

    Tries standard json.loads first, falls back to json_repair on failure.
    """
    try:
        return loads(text)
    except (JSONDecodeError, ValueError):
        import json_repair  # type: ignore[import-not-found]

        logger.debug("Standard JSON parse failed, attempting repair")
        return json_repair.loads(text)


class LLMProvider(abc.ABC):
    """Abstract LLM provider for structured extraction.

    Implementations use httpx to call provider APIs directly,
    consistent with the Jina embedding pattern (no SDK deps).
    """

    @abc.abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> tuple[str, Usage]:
        """Generate a text completion.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            temperature: Optional sampling temperature override.
            timeout: Optional per-call HTTP timeout (seconds).

        Returns:
            (text, usage) tuple.
        """

    @abc.abstractmethod
    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        """Generate a structured JSON response matching the given schema.

        Args:
            messages: List of message dicts with 'role' and 'content' keys.
            schema: JSON schema describing the expected output structure.
            timeout: Optional per-call HTTP timeout (seconds).

        Returns:
            (parsed, usage) tuple.
        """

    @abc.abstractmethod
    async def close(self) -> None:
        """Close the underlying HTTP client."""
