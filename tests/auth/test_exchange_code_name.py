from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.workos_authkit import exchange_code_for_user
from context_service.config.settings import Settings

_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)


def _fake_workos(first: str | None, last: str | None) -> MagicMock:
    user = MagicMock()
    user.id = "wos-user-1"
    user.email = "alice@example.com"
    user.first_name = first
    user.last_name = last
    resp = MagicMock()
    resp.user = user
    resp.organization_id = None
    client = MagicMock()
    client.user_management.authenticate_with_code.return_value = resp
    mod = MagicMock()
    mod.WorkOSClient.return_value = client
    return mod


@pytest.mark.asyncio
async def test_exchange_returns_joined_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("context_service.auth.workos_authkit.get_settings", lambda: _SETTINGS)
    with patch.dict(sys.modules, {"workos": _fake_workos("Alice", "Example")}):
        info = await exchange_code_for_user("code-123")
    assert info["name"] == "Alice Example"
    assert info["organization_id"] is None


@pytest.mark.asyncio
async def test_exchange_name_is_none_when_no_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("context_service.auth.workos_authkit.get_settings", lambda: _SETTINGS)
    with patch.dict(sys.modules, {"workos": _fake_workos(None, None)}):
        info = await exchange_code_for_user("code-123")
    assert info["name"] is None
