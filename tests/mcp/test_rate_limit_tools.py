"""Tests for MCP tool rate limiting."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.api.rate_limit import RateLimitExceeded
from context_service.auth.context import AuthContext


class TestRateLimitDecorator:
    @pytest.fixture
    def mock_auth(self) -> AuthContext:
        return AuthContext(
            org_id="test_org",
            user_id="test_user",
            email="test@example.com",
            is_dev=False,
        )

    async def test_decorator_checks_rate_limit(self, mock_auth: AuthContext) -> None:
        from context_service.mcp.rate_limit import rate_limited

        @rate_limited("test_tool")
        async def my_tool() -> dict:
            return {"result": "ok"}

        with (
            patch(
                "context_service.mcp.rate_limit.get_mcp_auth_context",
                new_callable=AsyncMock,
                return_value=mock_auth,
            ),
            patch(
                "context_service.mcp.rate_limit._check_rate_limit",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            mock_check.return_value = MagicMock(limit=100, remaining=99)
            result = await my_tool()

            mock_check.assert_called_once_with(mock_auth, "test_tool")
            assert result["result"] == "ok"

    async def test_decorator_raises_on_limit_exceeded(self, mock_auth: AuthContext) -> None:
        from context_service.mcp.rate_limit import rate_limited

        @rate_limited("test_tool")
        async def my_tool() -> dict:
            return {"result": "ok"}

        with (
            patch(
                "context_service.mcp.rate_limit.get_mcp_auth_context",
                new_callable=AsyncMock,
                return_value=mock_auth,
            ),
            patch(
                "context_service.mcp.rate_limit._check_rate_limit",
                new_callable=AsyncMock,
            ) as mock_check,
        ):
            mock_check.side_effect = RateLimitExceeded(
                retry_after=30,
                limit=20,
                current=21,
                category="mcp_write",
            )

            with pytest.raises(RateLimitExceeded):
                await my_tool()

    async def test_no_rate_limiter_allows_request(self, mock_auth: AuthContext) -> None:
        """When _rate_limiter is None, _check_rate_limit returns unlimited headers."""
        import context_service.mcp.rate_limit as rl_module
        from context_service.mcp.rate_limit import _check_rate_limit

        original = rl_module._rate_limiter
        try:
            rl_module._rate_limiter = None
            headers = await _check_rate_limit(mock_auth, "remember")
            assert headers.limit == 9999
            assert headers.remaining == 9999
            assert headers.policy == "unlimited/remember"
        finally:
            rl_module._rate_limiter = original

    async def test_set_mcp_rate_limiter(self) -> None:
        """set_mcp_rate_limiter registers a RateLimiter backed by the given Redis client."""
        import context_service.mcp.rate_limit as rl_module
        from context_service.mcp.rate_limit import set_mcp_rate_limiter

        mock_redis = MagicMock()
        original = rl_module._rate_limiter
        try:
            set_mcp_rate_limiter(mock_redis)
            assert rl_module._rate_limiter is not None
        finally:
            rl_module._rate_limiter = original
