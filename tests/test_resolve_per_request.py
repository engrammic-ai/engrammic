"""Per-request MCP auth resolution: end-to-end behavior of get_mcp_auth_context.

Pins the integration of FastMCP's `get_http_headers()` with the
WorkOS-backed `resolve_mcp_auth_from_header` resolver and the dev fallback.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.context import AuthContext
from context_service.auth.resolve import MCPAuthError
from context_service.config.settings import Settings
from context_service.mcp import server

_AUTH_ON = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)

_AUTH_OFF = Settings(_env_file=None, auth_enabled=False)


@pytest.mark.asyncio
async def test_header_reaches_verify_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A live Authorization header is forwarded to WorkOS for verification."""
    monkeypatch.setattr(
        server, "get_http_headers", lambda **_kw: {"authorization": "Bearer sealed-abc"}
    )
    base = AuthContext(org_id="org-1", user_id="user-1", email="x@y.com", is_dev=False)
    verify = AsyncMock(return_value=base)
    with patch("context_service.auth.workos_client.verify_session", new=verify):
        ctx = await server.get_mcp_auth_context()

    assert ctx.org_id == base.org_id
    assert ctx.user_id == base.user_id
    assert ctx.email == base.email
    assert ctx.is_dev == base.is_dev
    verify.assert_awaited_once_with("sealed-abc")


@pytest.mark.asyncio
async def test_malformed_bearer_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_http_headers", lambda **_kw: {"authorization": "NotBearer xxx"}
    )
    with pytest.raises(MCPAuthError, match="Invalid Authorization header format"):
        await server.get_mcp_auth_context()


@pytest.mark.asyncio
async def test_missing_header_raises_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_http_headers", lambda **_kw: {})
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("WORKOS_API_KEY", "test-key")
    monkeypatch.setenv("WORKOS_CLIENT_ID", "test-client")
    monkeypatch.setenv("WORKOS_COOKIE_PASSWORD", "test-cookie-password-32-bytes-min!")
    auth_on = Settings(_env_file=None)
    with (
        patch("context_service.config.settings.get_settings", return_value=auth_on),
        pytest.raises(MCPAuthError, match="Missing Authorization header"),
    ):
        await server.get_mcp_auth_context()


@pytest.mark.asyncio
async def test_missing_header_returns_dev_when_auth_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, "get_http_headers", lambda **_kw: {})
    with patch("context_service.config.settings.get_settings", return_value=_AUTH_OFF):
        ctx = await server.get_mcp_auth_context()

    assert ctx.is_dev is True
    assert ctx.org_id == _AUTH_OFF.dev_org_id
    assert ctx.user_id == _AUTH_OFF.dev_user_id


@pytest.mark.asyncio
async def test_empty_bearer_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_http_headers", lambda **_kw: {"authorization": "Bearer    "})
    with pytest.raises(MCPAuthError, match="Empty bearer token"):
        await server.get_mcp_auth_context()
