"""Tests for the rate limiter service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.rate_limit import (
    RateLimitCategory,
    RateLimiter,
    RateLimitExceeded,
    RateLimitHeaders,
    get_tool_category,
)
from context_service.auth.context import AuthContext  # noqa: E402


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.incr_with_expire = AsyncMock(return_value=1)
    redis._redis = AsyncMock()
    redis._redis.get = AsyncMock(return_value=None)
    redis._redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.security.rate_limit.enabled = True
    settings.security.rate_limit.default_tier = "free"
    settings.security.rate_limit.tier_cache_ttl_seconds = 300
    settings.security.rate_limit.get_limits.return_value = MagicMock(
        mcp_write=MagicMock(requests_per_minute=20, requests_per_hour=200),
        mcp_read=MagicMock(requests_per_minute=60, requests_per_hour=600),
    )
    return settings


@pytest.fixture
def auth_context() -> AuthContext:
    return AuthContext(
        org_id="org_123",
        user_id="user_456",
        email="test@example.com",
        is_dev=False,
    )


class TestGetToolCategory:
    def test_write_tools(self) -> None:
        for tool in [
            "remember",
            "learn",
            "believe",
            "link",
            "reason",
            "reflect",
            "hypothesize",
            "revise",
            "commit",
        ]:
            assert get_tool_category(tool) == RateLimitCategory.MCP_WRITE

    def test_read_tools(self) -> None:
        for tool in ["recall", "trace", "patterns"]:
            assert get_tool_category(tool) == RateLimitCategory.MCP_READ

    def test_unknown_defaults_to_write(self) -> None:
        assert get_tool_category("unknown_tool") == RateLimitCategory.MCP_WRITE


class TestRateLimiter:
    async def test_check_returns_headers_when_within_limit(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert isinstance(headers, RateLimitHeaders)
        assert headers.remaining > 0

    async def test_check_raises_when_limit_exceeded(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_redis.incr_with_expire = AsyncMock(return_value=21)  # Over 20 RPM limit

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)

            with pytest.raises(RateLimitExceeded) as exc_info:
                await limiter.check(
                    org_id=auth_context.org_id,
                    user_id=auth_context.user_id,
                    category=RateLimitCategory.MCP_WRITE,
                    is_dev=False,
                )

        assert exc_info.value.retry_after > 0

    async def test_dev_mode_skips_limiting(
        self, mock_redis: AsyncMock, mock_settings: MagicMock
    ) -> None:
        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id="dev_org",
                user_id="dev_user",
                category=RateLimitCategory.MCP_WRITE,
                is_dev=True,
            )

        assert headers.remaining == headers.limit
        mock_redis.incr_with_expire.assert_not_called()

    async def test_disabled_rate_limiting_skips_check(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_settings.security.rate_limit.enabled = False

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert headers.remaining == headers.limit
        mock_redis.incr_with_expire.assert_not_called()

    async def test_redis_failure_fails_open(
        self, mock_redis: AsyncMock, mock_settings: MagicMock, auth_context: AuthContext
    ) -> None:
        mock_redis.incr_with_expire = AsyncMock(return_value=0)  # Circuit open returns 0

        with patch("context_service.api.rate_limit.get_settings", return_value=mock_settings):
            limiter = RateLimiter(mock_redis)
            headers = await limiter.check(
                org_id=auth_context.org_id,
                user_id=auth_context.user_id,
                category=RateLimitCategory.MCP_WRITE,
                is_dev=False,
            )

        assert headers.remaining == headers.limit
