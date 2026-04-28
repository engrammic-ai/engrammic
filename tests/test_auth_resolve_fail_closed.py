"""Regression tests: per-request MCP auth must fail closed.

The resolver `resolve_mcp_auth_from_header` is the per-call WorkOS verification
helper used by `mcp.server.get_mcp_auth_context`. Silent fallback to a dev
AuthContext when AUTH_ENABLED=true would defeat the boot-time prod-guard in
Settings, so missing/malformed headers and rejected tokens must raise
``MCPAuthError``.

The dev fallback (AUTH_ENABLED=false, no header) lives in
``mcp.server.get_mcp_auth_context`` and is pinned in
``tests/test_resolve_per_request.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.auth.context import AuthContext
from context_service.auth.resolve import MCPAuthError, resolve_mcp_auth_from_header


class TestResolveMCPAuthFromHeaderFailClosed:
    async def test_empty_header_raises(self) -> None:
        with pytest.raises(MCPAuthError, match="Missing Authorization header"):
            await resolve_mcp_auth_from_header("")

    async def test_malformed_header_raises(self) -> None:
        with pytest.raises(MCPAuthError, match="Invalid Authorization header format"):
            await resolve_mcp_auth_from_header("NotBearer abc")

    async def test_wrong_scheme_raises(self) -> None:
        with pytest.raises(MCPAuthError, match="Invalid Authorization header format"):
            await resolve_mcp_auth_from_header("Basic dXNlcjpwYXNz")

    async def test_empty_token_raises(self) -> None:
        with pytest.raises(MCPAuthError, match="Empty bearer token"):
            await resolve_mcp_auth_from_header("Bearer    ")

    async def test_workos_rejection_raises(self) -> None:
        with (
            patch(
                "context_service.auth.workos_client.verify_session",
                new=AsyncMock(side_effect=ValueError("token expired")),
            ),
            pytest.raises(MCPAuthError, match="rejected by WorkOS"),
        ):
            await resolve_mcp_auth_from_header("Bearer bogus")

    async def test_valid_token_returns_workos_context(self) -> None:
        mock_ctx = AuthContext(org_id="org-1", user_id="user-1", email="x@y.com", is_dev=False)
        with patch(
            "context_service.auth.workos_client.verify_session",
            new=AsyncMock(return_value=mock_ctx),
        ) as verify:
            ctx = await resolve_mcp_auth_from_header("Bearer valid-sealed-session")

        assert ctx is mock_ctx
        assert ctx.is_dev is False
        verify.assert_awaited_once_with("valid-sealed-session")

    async def test_bearer_prefix_case_insensitive(self) -> None:
        mock_ctx = AuthContext(org_id="org-1", user_id="user-1", email=None, is_dev=False)
        with patch(
            "context_service.auth.workos_client.verify_session",
            new=AsyncMock(return_value=mock_ctx),
        ):
            ctx = await resolve_mcp_auth_from_header("bearer some-token")
        assert ctx is mock_ctx
