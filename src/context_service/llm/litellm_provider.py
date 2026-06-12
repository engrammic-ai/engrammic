"""LiteLLM-based LLM provider - unified interface for all providers."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from context_service.llm.google_genai_provider import GoogleGenAIProvider

import litellm
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads
from context_service.telemetry.metrics import record_llm_call

logger = get_logger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

# Retry decorator for transient LLM API errors (429/503)
_llm_retry = retry(
    retry=retry_if_exception_type(
        (
            litellm.RateLimitError,
            litellm.ServiceUnavailableError,
        )
    ),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


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
        from context_service.config.settings import get_settings

        kwargs: dict[str, Any] = {}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._api_base:
            kwargs["api_base"] = self._api_base
        # Apply default timeout from settings when caller passes None
        if timeout is not None:
            kwargs["timeout"] = timeout
        else:
            kwargs["timeout"] = get_settings().llm.default_timeout_seconds
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

        @_llm_retry
        async def _call() -> Any:
            return await litellm.acompletion(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                **kwargs,
            )

        _start = time.perf_counter()
        try:
            response = await _call()
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=True)
        except Exception as e:
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=False)
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

        # Use json_schema for providers that support it, fall back to json_object
        if schema and self._model.startswith(("openai/", "anthropic/")):
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "extraction_result", "schema": schema, "strict": True},
            }
        else:
            kwargs["response_format"] = {"type": "json_object"}

        @_llm_retry
        async def _call() -> Any:
            return await litellm.acompletion(
                model=self._model,
                messages=messages,
                max_tokens=max_tokens,
                **kwargs,
            )

        _start = time.perf_counter()
        try:
            response = await _call()
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=True)
        except Exception as e:
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=False)
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
) -> LiteLLMProvider | GoogleGenAIProvider:
    """Factory for LiteLLM provider by provider name.

    Args:
        provider: One of "anthropic", "openai", "vertex_gemini", "vertex", "gemini", "ollama".
        model: Optional model name (without provider prefix). Falls back to models.yaml default.

    Returns:
        Configured LiteLLMProvider instance.
    """
    from context_service.config.settings import get_settings

    settings = get_settings()

    def _default_model() -> str:
        """Get default model from models.yaml."""
        spec = settings.models.get_model("default")
        return spec.model

    # Map provider to litellm model prefix and get API key
    if provider == "anthropic":
        api_key = (
            settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else None
        )
        model_name = model or _default_model()
        litellm_model = f"anthropic/{model_name}"
        return LiteLLMProvider(model=litellm_model, api_key=api_key)

    if provider == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
        model_name = model or _default_model()
        litellm_model = f"openai/{model_name}"
        return LiteLLMProvider(model=litellm_model, api_key=api_key)

    if provider in ("vertex_gemini", "vertex", "vertex_ai"):
        model_name = model or _default_model()
        # Gemini 3.x requires google-genai SDK with enterprise mode
        if model_name.startswith("gemini-3"):
            from context_service.llm.google_genai_provider import build_google_genai_provider

            return build_google_genai_provider(model_name)
        # 2.x and earlier use Vertex AI REST API
        project = (
            settings.models.vertex_project or settings.vertex_project or settings.vertex_project_id
        )
        location = settings.models.vertex_location
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
    model_name = model or _default_model()
    litellm_model = f"gemini/{model_name}"
    return LiteLLMProvider(model=litellm_model, api_key=api_key)
