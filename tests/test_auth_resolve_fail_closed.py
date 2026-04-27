"""Regression tests: MCP auth resolver must fail closed when AUTH_ENABLED=true.

Silent fallback to a dev AuthContext under AUTH_ENABLED=true would defeat the
boot-time prod-guard in Settings. These tests pin the fail-closed behavior.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import context_service.auth.resolve as resolve_mod
from context_service.auth.context import AuthContext
from context_service.auth.resolve import MCPAuthError, resolve_mcp_auth
from context_service.config.settings import Settings

_AUTH_ON = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key="test-key",
    workos_client_id="test-client",
)

_AUTH_OFF = Settings(_env_file=None, auth_enabled=False)


class TestResolveMCPAuthFailClosed:
    async def test_missing_token_raises_when_auth_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.auth.resolve.get_settings", lambda: _AUTH_ON)
        monkeypatch.delenv("MCP_DEV_TOKEN", raising=False)

        with pytest.raises(MCPAuthError, match="MCP_DEV_TOKEN not set"):
            await resolve_mcp_auth()

    async def test_invalid_token_raises_when_auth_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.auth.resolve.get_settings", lambda: _AUTH_ON)
        monkeypatch.setenv("MCP_DEV_TOKEN", "bogus")

        with (
            patch(
                "context_service.auth.workos_client.verify_session",
                new=AsyncMock(side_effect=ValueError("token expired")),
            ),
            pytest.raises(MCPAuthError, match="rejected by WorkOS"),
        ):
            await resolve_mcp_auth()

    async def test_dev_bypass_returns_dev_context_when_auth_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.auth.resolve.get_settings", lambda: _AUTH_OFF)
        resolve_mod._dev_bypass_logged = False

        ctx = await resolve_mcp_auth()

        assert isinstance(ctx, AuthContext)
        assert ctx.is_dev is True

    async def test_valid_token_returns_workos_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.auth.resolve.get_settings", lambda: _AUTH_ON)
        monkeypatch.setenv("MCP_DEV_TOKEN", "valid")

        mock_ctx = AuthContext(
            org_id="org-1", user_id="user-1", email="x@y.com", is_dev=False
        )
        with patch(
            "context_service.auth.workos_client.verify_session",
            new=AsyncMock(return_value=mock_ctx),
        ):
            ctx = await resolve_mcp_auth()

        assert ctx is mock_ctx
        assert ctx.is_dev is False
