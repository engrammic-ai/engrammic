"""Tests for the prod-guard validator in Settings."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import ValidationError

from context_service.config.settings import Settings


def make_settings(**env_overrides: str) -> Settings:
    """Construct a Settings instance with specific env vars patched in."""
    base = {
        "ENVIRONMENT": "development",
        "AUTH_ENABLED": "false",
    }
    base.update(env_overrides)
    with patch.dict("os.environ", base, clear=False):
        return Settings(_env_file=None)


class TestProdGuard:
    def test_production_without_auth_raises(self) -> None:
        with pytest.raises(ValidationError, match="AUTH_ENABLED must be true"):
            make_settings(ENVIRONMENT="production", AUTH_ENABLED="false")

    def test_production_with_auth_and_keys_ok(self) -> None:
        s = make_settings(
            ENVIRONMENT="production",
            AUTH_ENABLED="true",
            WORKOS_API_KEY="key-abc",
            WORKOS_CLIENT_ID="client-xyz",
            WORKOS_COOKIE_PASSWORD="cookie-pw-32-bytes-min-padding!!",
        )
        assert s.auth_enabled is True
        assert s.environment == "production"

    def test_auth_enabled_without_workos_key_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_API_KEY"):
            make_settings(AUTH_ENABLED="true", WORKOS_CLIENT_ID="client-xyz")

    def test_auth_enabled_without_workos_client_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_API_KEY"):
            make_settings(AUTH_ENABLED="true", WORKOS_API_KEY="key-abc")

    def test_auth_enabled_without_cookie_password_raises(self) -> None:
        with pytest.raises(ValidationError, match="WORKOS_COOKIE_PASSWORD"):
            make_settings(
                AUTH_ENABLED="true",
                WORKOS_API_KEY="key-abc",
                WORKOS_CLIENT_ID="client-xyz",
            )

    def test_auth_enabled_with_all_keys_ok(self) -> None:
        s = make_settings(
            AUTH_ENABLED="true",
            WORKOS_API_KEY="key-abc",
            WORKOS_CLIENT_ID="client-xyz",
            WORKOS_COOKIE_PASSWORD="cookie-pw-32-bytes-min-padding!!",
        )
        assert s.auth_enabled is True

    def test_dev_environment_auth_disabled_ok(self) -> None:
        s = make_settings(ENVIRONMENT="development", AUTH_ENABLED="false")
        assert s.auth_enabled is False
