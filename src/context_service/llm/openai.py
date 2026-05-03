"""OpenAI LLM provider using httpx (no SDK dependency)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads

logger = get_logger(__name__)


class OpenAIError(Exception):
    """Raised when OpenAI API operations fail."""


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible LLM provider using httpx.

    Uses JSON mode for structured output extraction.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        api_url: str = "https://api.openai.com/v1/chat/completions",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_url = api_url
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, model: str | None = None) -> OpenAIProvider:
        """Create provider from application settings."""
        settings = get_settings()
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
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

    async def _request_with_backoff(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        timeout: float | None = None,
    ) -> httpx.Response:
        """Make API request with exponential backoff on 429/5xx."""
        max_retries = 3
        post_kwargs: dict[str, Any] = {}
        if timeout is not None:
            post_kwargs["timeout"] = timeout

        for attempt in range(max_retries + 1):
            try:
                response = await client.post(self._api_url, json=payload, **post_kwargs)
                if response.status_code == 429 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "openai_rate_limited",
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                if 500 <= response.status_code < 600 and attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "openai_server_error",
                        status_code=response.status_code,
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError:
                raise
            except httpx.RequestError as e:
                if attempt < max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "openai_request_error",
                        error=str(e),
                        wait_seconds=wait,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
        raise OpenAIError("Max retries exceeded")

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
        try:
            response = await self._request_with_backoff(client, payload, timeout)
        except httpx.HTTPStatusError as e:
            logger.error(
                "OpenAI API error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise OpenAIError(f"OpenAI API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("OpenAI API request error", error=str(e))
            raise OpenAIError(f"Failed to connect to OpenAI API: {e}") from e

        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise OpenAIError(
                f"Unexpected response structure: missing 'choices' in {list(data.keys())}"
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise OpenAIError("No content in response message")
        usage = self._extract_usage(data)
        logger.debug("OpenAI completion", model=self._model, wall_ms=wall_ms)
        return str(content), usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        client = await self._get_client()
        payload = {
            "model": self._model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_result",
                    "schema": schema,
                    "strict": True,
                },
            },
        }
        start = time.monotonic()
        try:
            response = await self._request_with_backoff(client, payload, timeout)
        except httpx.HTTPStatusError as e:
            logger.error(
                "OpenAI API error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise OpenAIError(f"OpenAI API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("OpenAI API request error", error=str(e))
            raise OpenAIError(f"Failed to connect to OpenAI API: {e}") from e

        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise OpenAIError(
                f"Unexpected response structure: missing 'choices' in {list(data.keys())}"
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise OpenAIError("No content in response message")
        result: dict[str, Any] = robust_json_loads(content)
        usage = self._extract_usage(data)
        logger.debug("OpenAI extract_structured", model=self._model, wall_ms=wall_ms)
        return result, usage

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
