"""Integration tests for WorkOS auth dependency (mocked SDK)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from context_service.api.auth_dep import get_auth_context
from context_service.auth.context import AuthContext
from context_service.config.settings import Settings


def _make_request(auth_header: str | None = None) -> object:
    """Return a minimal request-like object."""

    class _Headers(dict):  # type: ignore[type-arg]
        def get(self, key: str, default: str = "") -> str:
            return super().get(key, default)

    class _Request:
        headers = _Headers({"Authorization": auth_header} if auth_header else {})

    return _Request()


_WORKOS_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)

_MOCK_AUTH_CTX = AuthContext(
    org_id="org-123",
    user_id="user-456",
    email="test@example.com",
    is_dev=False,
)


@pytest.mark.integration
class TestWorkOSAuthDependency:
    async def test_valid_token_returns_auth_context(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with patch(
            "context_service.auth.workos_client.verify_session",
            new=AsyncMock(return_value=_MOCK_AUTH_CTX),
        ):
            ctx = await get_auth_context(_make_request("Bearer valid-token"))  # type: ignore[arg-type]

        assert ctx.org_id == "org-123"
        assert ctx.user_id == "user-456"
        assert ctx.email == "test@example.com"
        assert ctx.is_dev is False

    async def test_invalid_token_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with (
            patch(
                "context_service.auth.workos_client.verify_session",
                new=AsyncMock(side_effect=ValueError("token expired")),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_auth_context(_make_request("Bearer bad-token"))  # type: ignore[arg-type]

        assert exc_info.value.status_code == 401
        assert "token expired" in str(exc_info.value.detail)

    async def test_missing_authorization_header_raises_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_make_request())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 401
        assert "Authorization" in exc_info.value.detail

    async def test_malformed_authorization_header_raises_401(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_make_request("Basic dXNlcjpwYXNz"))  # type: ignore[arg-type]

        assert exc_info.value.status_code == 401
