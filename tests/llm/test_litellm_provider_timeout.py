"""Tests for LiteLLM provider timeout defaults (E-03/E-04/E-05/AI-02 fix)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.llm.litellm_provider import LiteLLMProvider


def _make_settings(default_timeout: float = 60.0) -> MagicMock:
    settings = MagicMock()
    settings.llm.default_timeout_seconds = default_timeout
    return settings


@pytest.mark.asyncio
async def test_complete_applies_default_timeout_when_none() -> None:
    """Verify that complete() uses settings default when timeout=None."""
    provider = LiteLLMProvider(model="test/model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test response"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

    with (
        patch(
            "context_service.config.settings.get_settings",
            return_value=_make_settings(default_timeout=60.0),
        ),
        patch("context_service.llm.litellm_provider.litellm") as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        mock_litellm.RateLimitError = Exception
        mock_litellm.ServiceUnavailableError = Exception

        await provider.complete(
            messages=[{"role": "user", "content": "test"}],
            timeout=None,
        )

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["timeout"] == 60.0


@pytest.mark.asyncio
async def test_complete_uses_explicit_timeout_when_provided() -> None:
    """Verify that complete() uses explicit timeout when provided."""
    provider = LiteLLMProvider(model="test/model")

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "test response"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=20)

    with (
        patch(
            "context_service.config.settings.get_settings",
            return_value=_make_settings(default_timeout=60.0),
        ),
        patch("context_service.llm.litellm_provider.litellm") as mock_litellm,
    ):
        mock_litellm.acompletion = AsyncMock(return_value=mock_response)
        mock_litellm.RateLimitError = Exception
        mock_litellm.ServiceUnavailableError = Exception

        await provider.complete(
            messages=[{"role": "user", "content": "test"}],
            timeout=30.0,
        )

        call_kwargs = mock_litellm.acompletion.call_args.kwargs
        assert call_kwargs["timeout"] == 30.0
