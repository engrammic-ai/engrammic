"""Integration tests: combined auth flow covering dev bypass, WorkOS, and prod-guard."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError

from context_service.api.auth_dep import get_auth_context
from context_service.auth.context import AuthContext
from context_service.config.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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

_DEV_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=False,
)

_MOCK_AUTH_CTX = AuthContext(
    org_id="org-123",
    user_id="user-456",
    email="test@example.com",
    is_dev=False,
)


# ---------------------------------------------------------------------------
# Test 1: AUTH_ENABLED=false -> dev AuthContext returned
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDevBypass:
    async def test_dev_bypass_returns_dev_auth_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With AUTH_ENABLED=false any request gets a dev AuthContext."""
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _DEV_SETTINGS)

        ctx = await get_auth_context(_make_request())  # type: ignore[arg-type]

        assert ctx.is_dev is True
        assert ctx.org_id == _DEV_SETTINGS.dev_org_id
        assert ctx.user_id == _DEV_SETTINGS.dev_user_id

    async def test_dev_bypass_ignores_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bearer tokens are ignored when auth is disabled; dev context still returned."""
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _DEV_SETTINGS)

        ctx = await get_auth_context(  # type: ignore[arg-type]
            _make_request("Bearer some-token-that-would-normally-be-verified")
        )

        assert ctx.is_dev is True


# ---------------------------------------------------------------------------
# Test 2: AUTH_ENABLED=true + mocked WorkOS -> real AuthContext
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestWorkOSFlow:
    async def test_valid_token_returns_real_auth_context(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With AUTH_ENABLED=true and a valid token, WorkOS verify_session is called."""
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with patch(
            "context_service.auth.workos_client.verify_session",
            new=AsyncMock(return_value=_MOCK_AUTH_CTX),
        ):
            ctx = await get_auth_context(_make_request("Bearer valid-token"))  # type: ignore[arg-type]

        assert ctx.is_dev is False
        assert ctx.org_id == "org-123"
        assert ctx.user_id == "user-456"
        assert ctx.email == "test@example.com"

    async def test_invalid_token_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Expired / invalid token surfaces as HTTP 401."""
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

    async def test_missing_header_raises_401(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Missing Authorization header raises HTTP 401 when auth is enabled."""
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: _WORKOS_SETTINGS)
        with pytest.raises(HTTPException) as exc_info:
            await get_auth_context(_make_request())  # type: ignore[arg-type]

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# Test 3: ENVIRONMENT=production + AUTH_ENABLED=false -> boot-time refusal
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestProdGuard:
    def test_production_without_auth_raises_at_boot(self) -> None:
        """Settings validation must reject ENVIRONMENT=production AUTH_ENABLED=false."""
        with pytest.raises((ValueError, ValidationError)):
            Settings(
                _env_file=None,
                environment="production",
                auth_enabled=False,
            )

    def test_production_with_auth_and_workos_creds_is_valid(self) -> None:
        """ENVIRONMENT=production AUTH_ENABLED=true with full WorkOS creds is accepted."""
        settings = Settings(
            _env_file=None,
            environment="production",
            auth_enabled=True,
            workos_api_key=SecretStr("prod-key"),
            workos_client_id="prod-client",
            workos_cookie_password=SecretStr("prod-cookie-password-32-bytes-min!"),
        )

        assert settings.environment == "production"
        assert settings.auth_enabled is True
