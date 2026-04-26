"""Anthropic LLM provider using httpx (no SDK dependency)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.llm.base import LLMProvider, Usage, robust_json_loads

logger = get_logger(__name__)


class AnthropicError(Exception):
    """Raised when Anthropic API operations fail."""


class AnthropicProvider(LLMProvider):
    """Anthropic LLM provider using httpx.

    Uses tool_use for structured output extraction.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5-20250929",
        api_url: str = "https://api.anthropic.com/v1/messages",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._api_url = api_url
        self._client: httpx.AsyncClient | None = None

    @classmethod
    def from_settings(cls, model: str | None = None) -> AnthropicProvider:
        """Create provider from application settings."""
        settings = get_settings()
        return cls(
            api_key=settings.anthropic_api_key,
            model=model or "claude-sonnet-4-5-20250929",
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=60.0,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _extract_usage(self, data: dict[str, Any]) -> Usage:
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)
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

        system = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                user_messages.append(msg)

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": user_messages,
        }
        if system:
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature

        post_kwargs: dict[str, Any] = {}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        start = time.monotonic()
        try:
            response = await client.post(self._api_url, json=payload, **post_kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Anthropic API error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise AnthropicError(f"Anthropic API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("Anthropic API request error", error=str(e))
            raise AnthropicError(f"Failed to connect to Anthropic API: {e}") from e

        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        content_blocks = data.get("content")
        if not content_blocks or not isinstance(content_blocks, list):
            raise AnthropicError(
                f"Unexpected response: missing 'content' blocks in {list(data.keys())}"
            )
        text_parts = [block["text"] for block in content_blocks if block.get("type") == "text"]
        usage = self._extract_usage(data)
        logger.debug("Anthropic completion", model=self._model, wall_ms=wall_ms)
        return "".join(text_parts), usage

    async def extract_structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> tuple[dict[str, Any], Usage]:
        client = await self._get_client()

        system = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                user_messages.append(msg)

        tool = {
            "name": "extraction_result",
            "description": "Return the extracted entities and relationships.",
            "input_schema": schema,
        }

        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "messages": user_messages,
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": "extraction_result"},
        }
        if system:
            payload["system"] = system

        post_kwargs: dict[str, Any] = {}
        if timeout is not None:
            post_kwargs["timeout"] = timeout
        start = time.monotonic()
        try:
            response = await client.post(self._api_url, json=payload, **post_kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            logger.error(
                "Anthropic API error",
                status_code=e.response.status_code,
                response_text=e.response.text,
            )
            raise AnthropicError(f"Anthropic API request failed: {e}") from e
        except httpx.RequestError as e:
            logger.error("Anthropic API request error", error=str(e))
            raise AnthropicError(f"Failed to connect to Anthropic API: {e}") from e

        wall_ms = int((time.monotonic() - start) * 1000)
        data = response.json()
        content_blocks = data.get("content")
        if not content_blocks or not isinstance(content_blocks, list):
            raise AnthropicError(
                f"Unexpected response: missing 'content' blocks in {list(data.keys())}"
            )
        for block in content_blocks:
            if block["type"] == "tool_use" and block["name"] == "extraction_result":
                result: dict[str, Any] = block["input"]
                if isinstance(result, str):
                    result = robust_json_loads(result)
                usage = self._extract_usage(data)
                logger.debug("Anthropic extract_structured", model=self._model, wall_ms=wall_ms)
                return result, usage

        raise AnthropicError("No tool_use block found in response")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
