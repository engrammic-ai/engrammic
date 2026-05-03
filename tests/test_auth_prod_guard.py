"""Tests for the prod-guard validator in Settings."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from context_service.config.settings import Settings


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


