"""LiteLLM-based LLM provider - unified interface for all providers."""

from __future__ import annotations

from typing import Any

import litellm

from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads

logger = get_logger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True


class LiteLLMError(Exception):
    """Raised when LiteLLM operations fail."""


class LiteLLMProvider(LLMProvider):
    """Unified LLM provider using LiteLLM.

    Supports all providers: OpenAI, Anthropic, Gemini, Vertex AI, Ollama, vLLM, etc.
    Model format: "provider/model" (e.g., "anthropic/claude-3-opus", "openai/gpt-4o").
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__()
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._extra_kwargs = kwargs

    def _build_kwargs(
        self,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Build kwargs for litellm calls."""
        kwargs: dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if timeout:
            kwargs["timeout"] = timeout
        kwargs.update(self._extra_kwargs)
        return kwargs

    def _extract_usage(self, response: Any) -> Usage:
        """Extract usage from litellm response."""
        usage = getattr(response, "usage", None)
        if usage:
            return Usage(
                model=self._model,
                input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            )
        return Usage.zero(self._model)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        timeout: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[str, Usage]:
        """Generate a text completion via LiteLLM."""
        kwargs = self._build_kwargs(timeout=timeout)
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as e:
            logger.error("litellm_completion_failed", model=self._model, error=str(e))
            raise LiteLLMError(f"LiteLLM completion failed: {e}") from e

        content = response.choices[0].message.content or ""
        usage = self._extract_usage(response)
        self._record_usage(usage)

        # Check for truncation
        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            logger.warning("litellm_output_truncated", model=self._model, max_tokens=max_tokens)

        return content, usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], Usage]:
        """Generate structured JSON output via LiteLLM."""
        kwargs = self._build_kwargs(timeout=timeout)

        # Use JSON mode - litellm handles provider-specific format
        kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                **kwargs,
            )
        except Exception as e:
            logger.error("litellm_extract_failed", model=self._model, error=str(e))
            raise LiteLLMError(f"LiteLLM extraction failed: {e}") from e

        content = response.choices[0].message.content or "{}"
        usage = self._extract_usage(response)
        self._record_usage(usage)

        finish_reason = response.choices[0].finish_reason
        if finish_reason == "length":
            logger.warning("litellm_output_truncated", model=self._model, max_tokens=max_tokens)

        result = robust_json_loads(content)
        return result, usage

    async def close(self) -> None:
        """No-op for LiteLLM (no persistent client)."""
        pass


def build_litellm_provider(
    provider: str,
    model: str | None = None,
) -> LiteLLMProvider:
    """Factory for LiteLLM provider by provider name.

    Args:
        provider: One of "anthropic", "openai", "vertex_gemini", "gemini", "ollama".
        model: Optional model name (without provider prefix).

    Returns:
        Configured LiteLLMProvider instance.
    """
    from context_service.config.settings import get_settings

    settings = get_settings()

    # Map provider to litellm model prefix and get API key
    if provider == "anthropic":
        api_key = (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        model_name = model or "claude-sonnet-4-20250514"
        litellm_model = f"anthropic/{model_name}"
        return LiteLLMProvider(model=litellm_model, api_key=api_key)

    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        model_name = model or "gpt-4o"
        litellm_model = f"openai/{model_name}"
        return LiteLLMProvider(model=litellm_model, api_key=api_key)

    if provider == "vertex_gemini":
        # Vertex uses ADC, no API key needed
        model_name = model or "gemini-2.0-flash"
        project = settings.vertex_project or settings.vertex_project_id
        location = settings.vertex_location or "us-central1"
        litellm_model = f"vertex_ai/{model_name}"
        return LiteLLMProvider(
            model=litellm_model,
            vertex_project=project,
            vertex_location=location,
        )

    if provider == "ollama":
        model_name = model or "llama3"
        api_base = settings.ollama_base_url or "http://localhost:11434"
        litellm_model = f"ollama/{model_name}"
        return LiteLLMProvider(model=litellm_model, api_base=api_base)

    # Default: gemini via API key
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None
    model_name = model or settings.default_llm_model or "gemini-2.0-flash"
    litellm_model = f"gemini/{model_name}"
    return LiteLLMProvider(model=litellm_model, api_key=api_key)
