"""Google GenAI SDK provider for Gemini 3.x models with enterprise mode."""

from __future__ import annotations

import time
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads
from context_service.telemetry.metrics import record_llm_call

logger = get_logger(__name__)


class GoogleGenAIError(Exception):
    """Raised when Google GenAI operations fail."""


_genai_retry = retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)


class GoogleGenAIProvider(LLMProvider):
    """LLM provider using google-genai SDK with enterprise=True.

    Required for Gemini 3.x models which aren't available via Vertex AI REST API
    without allowlist access. Supports both API key and ADC (on GCP).
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        vertexai: bool = False,
        project: str | None = None,
        location: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__()
        self._model = model
        self._api_key = api_key
        self._vertexai = vertexai
        self._project = project
        self._location = location
        self._timeout = timeout
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init the genai client."""
        if self._client is None:
            from google import genai

            if self._vertexai:
                self._client = genai.Client(
                    vertexai=True,
                    project=self._project,
                    location=self._location,
                )
            else:
                self._client = genai.Client(enterprise=True, api_key=self._api_key)
        return self._client

    def _extract_usage(self, response: Any) -> Usage:
        """Extract usage from genai response."""
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            return Usage(
                model=self._model,
                input_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                output_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
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
        """Generate completion via google-genai SDK."""
        from google.genai import types

        client = self._get_client()

        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                role = "user"
            elif role == "assistant":
                role = "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        effective_timeout = timeout if timeout is not None else self._timeout
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            http_options=types.HttpOptions(timeout=int(effective_timeout * 1000)),
        )
        if temperature is not None:
            config.temperature = temperature

        @_genai_retry
        def _call() -> Any:
            return client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

        _start = time.perf_counter()
        try:
            response = _call()
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=True)
        except Exception as e:
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=False)
            logger.error("google_genai_completion_failed", model=self._model, error=str(e))
            raise GoogleGenAIError(f"Google GenAI completion failed: {e}") from e

        content = response.text or ""
        usage = self._extract_usage(response)
        self._record_usage(usage)

        return content, usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], Usage]:
        """Generate structured JSON via google-genai SDK."""
        from google.genai import types

        client = self._get_client()

        contents = []
        for msg in messages:
            role = msg["role"]
            if role == "system":
                role = "user"
            elif role == "assistant":
                role = "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        effective_timeout = timeout if timeout is not None else self._timeout
        config = types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_schema=schema,
            http_options=types.HttpOptions(timeout=int(effective_timeout * 1000)),
        )

        @_genai_retry
        def _call() -> Any:
            return client.models.generate_content(
                model=self._model,
                contents=contents,
                config=config,
            )

        _start = time.perf_counter()
        try:
            response = _call()
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=True)
        except Exception as e:
            record_llm_call(self._model, (time.perf_counter() - _start) * 1000, success=False)
            logger.error("google_genai_extract_failed", model=self._model, error=str(e))
            raise GoogleGenAIError(f"Google GenAI extraction failed: {e}") from e

        content = response.text or "{}"
        usage = self._extract_usage(response)
        self._record_usage(usage)

        result = robust_json_loads(content)
        return result, usage

    async def close(self) -> None:
        """No persistent client to close."""
        pass


def build_google_genai_provider(model: str) -> GoogleGenAIProvider:
    """Factory for Google GenAI provider.

    Uses enterprise mode with API key for Gemini 3.x (required until Vertex AI
    allowlist is granted). Falls back to Vertex AI mode for 2.x models.

    Args:
        model: Model name (e.g., "gemini-3.1-flash-lite", "gemini-3.1-pro").

    Returns:
        Configured GoogleGenAIProvider instance.
    """
    from context_service.config.settings import get_settings

    settings = get_settings()
    api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if api_key:
        return GoogleGenAIProvider(
            model=model,
            api_key=api_key,
            timeout=settings.llm.default_timeout_seconds,
        )

    project = (
        settings.models.vertex_project or settings.vertex_project or settings.vertex_project_id
    )
    location = settings.models.vertex_location or "us-central1"

    if project:
        return GoogleGenAIProvider(
            model=model,
            vertexai=True,
            project=project,
            location=location,
            timeout=settings.llm.default_timeout_seconds,
        )

    raise GoogleGenAIError("GEMINI_API_KEY required for Gemini 3.x models")
