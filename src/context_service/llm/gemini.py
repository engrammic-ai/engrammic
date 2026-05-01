"""Google Gemini LLM provider using httpx (OpenAI-compatible endpoint)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads

logger = get_logger(__name__)

_RETRY_DELAYS = (0.5, 1.5)


class GeminiError(Exception):
    """Raised when Gemini API operations fail."""


class GeminiProvider(LLMProvider):
    """Gemini LLM provider using the OpenAI-compatible endpoint.

    Uses JSON mode for structured output extraction.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.0-flash",
        api_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_url = api_url
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, model: str | None = None) -> GeminiProvider:
        """Create provider from application settings."""
        settings = get_settings()
        api_key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else ""
        return cls(
            api_key=api_key,
            model=model or settings.default_llm_model,
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _post_with_retry(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        """POST to the Gemini API with retry on transient httpx.RequestError."""
        last_exc: httpx.RequestError | None = None
        post_kwargs: dict[str, Any] = {}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                response = await client.post(self._api_url, json=payload, **post_kwargs)
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Gemini API error",
                    status_code=e.response.status_code,
                    response_text=e.response.text,
                )
                raise GeminiError(f"Gemini API request failed: {type(e).__name__}: {e!r}") from e
            except httpx.RequestError as e:
                last_exc = e
                if attempt < len(_RETRY_DELAYS):
                    delay = _RETRY_DELAYS[attempt]
                    logger.warning(
                        "Gemini retry",
                        attempt=attempt + 1,
                        max_attempts=len(_RETRY_DELAYS),
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error("Gemini API request error", error=str(e))
                raise GeminiError(
                    f"Failed to connect to Gemini API: {type(e).__name__}: {e!r}"
                ) from e
        assert last_exc is not None
        raise GeminiError(
            f"Failed to connect to Gemini API: {type(last_exc).__name__}: {last_exc!r}"
        ) from last_exc

    def _extract_usage(self, data: dict[str, Any]) -> Usage:
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("prompt_tokens") or 0)
        output_tokens = int(usage.get("completion_tokens") or 0)
        return Usage(
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> tuple[str, Usage]:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        start = time.monotonic()
        response = await self._post_with_retry(client, payload, timeout=timeout)
        wall_ms = int((time.monotonic() - start) * 1000)

        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise GeminiError(
                f"Unexpected response structure: missing 'choices' in {list(data.keys())}"
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise GeminiError("No content in response message")
        usage = self._extract_usage(data)
        logger.debug("Gemini completion", model=self._model, wall_ms=wall_ms)
        return str(content), usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],  # noqa: ARG002
        *,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        start = time.monotonic()
        response = await self._post_with_retry(client, payload, timeout=timeout)
        wall_ms = int((time.monotonic() - start) * 1000)

        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise GeminiError(
                f"Unexpected response structure: missing 'choices' in {list(data.keys())}"
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise GeminiError("No content in response message")
        result: dict[str, Any] = robust_json_loads(content)
        usage = self._extract_usage(data)
        logger.debug("Gemini extract_structured", model=self._model, wall_ms=wall_ms)
        return result, usage

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
