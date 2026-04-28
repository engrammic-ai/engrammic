"""Tests for the prod-guard validator in Settings."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from context_service.config.settings import Settings, get_settings
from context_service.mcp.auth import (
    ALL_PERMISSIONS,
    DEV_ORG_ID,
    MCPAuthError,
    validate_mcp_request,
)


class TestProdGuard:
    def test_production_without_auth_raises(self) -> None:
        with pytest.raises(ValidationError, match="AUTH_ENABLED must be true"):
            Settings(_env_file=None, environment="production", auth_enabled=False)

    def test_production_with_auth_and_keys_ok(self) -> None:
        s = Settings(
            _env_file=None,
            environment="production",
            auth_enabled=True,
            workos_api_key=SecretStr("key-abc"),
            workos_client_id="client-xyz",
            workos_cookie_password=SecretStr("cookie-pw-32-bytes-min-padding!!"),
        )
        assert s.auth_enabled is True
        assert s.environment == "production"

    def test_auth_enabled_without_workos_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_API_KEY"):
            Settings(_env_file=None, auth_enabled=True, workos_client_id="client-xyz")

    def test_auth_enabled_without_workos_client_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_API_KEY"):
            Settings(_env_file=None, auth_enabled=True, workos_api_key=SecretStr("key-abc"))

    def test_auth_enabled_without_cookie_password_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_COOKIE_PASSWORD"):
            Settings(
                _env_file=None,
                auth_enabled=True,
                workos_api_key=SecretStr("key-abc"),
                workos_client_id="client-xyz",
            )

    def test_auth_enabled_with_all_keys_ok(self) -> None:
        s = Settings(
            _env_file=None,
            auth_enabled=True,
            workos_api_key=SecretStr("key-abc"),
            workos_client_id="client-xyz",
            workos_cookie_password=SecretStr("cookie-pw-32-bytes-min-padding!!"),
        )
        assert s.auth_enabled is True

    def test_dev_environment_auth_disabled_ok(self) -> None:
        s = Settings(_env_file=None, environment="development", auth_enabled=False)
        assert s.auth_enabled is False


class TestMCPRequestLayerGuard:
    """Tests for ``validate_mcp_request`` covering S-002 and S-004."""

    def _patch_settings(
        self, monkeypatch: pytest.MonkeyPatch, environment: str
    ) -> None:
        is_prod = environment == "production"
        settings = Settings(
            _env_file=None,
            environment=environment,
            auth_enabled=is_prod,
            workos_api_key=SecretStr("key-abc") if is_prod else None,
            workos_client_id="client-xyz" if is_prod else None,
            workos_cookie_password=(
                SecretStr("cookie-pw-32-bytes-min-padding!!") if is_prod else None
            ),
        )
        # ``get_settings`` is lru_cached; patch it at the auth module's
        # call site so each test sees a fresh Settings instance.
        monkeypatch.setattr(
            "context_service.mcp.auth.get_settings", lambda: settings
        )
        get_settings.cache_clear()

    async def test_request_layer_prod_guard_raises_when_api_key_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        self._patch_settings(monkeypatch, "production")

        with pytest.raises(MCPAuthError, match="MCP_API_KEY"):
            await validate_mcp_request(authorization=None)

    async def test_dev_fallback_works_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MCP_API_KEY", raising=False)
        self._patch_settings(monkeypatch, "development")

        ctx = await validate_mcp_request(authorization=None)

        assert ctx.org_id == DEV_ORG_ID
        assert ctx.is_dev_mode is True
        assert ctx.permissions == list(ALL_PERMISSIONS)

    async def test_timing_safe_compare_accepts_valid_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_API_KEY", "secret-key")
        monkeypatch.setenv("MCP_ORG_ID", "acme")
        self._patch_settings(monkeypatch, "development")

        ctx = await validate_mcp_request(authorization="Bearer secret-key")

        assert ctx.org_id == "acme"
        assert ctx.is_dev_mode is False
        assert ctx.permissions == list(ALL_PERMISSIONS)

    async def test_timing_safe_compare_rejects_invalid_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MCP_API_KEY", "secret-key")
        self._patch_settings(monkeypatch, "development")

        with pytest.raises(MCPAuthError, match="Invalid API key"):
            await validate_mcp_request(authorization="Bearer wrong-key")
