"""Tests for auth dev bypass (AUTH_ENABLED=false)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import context_service.api.auth_dep as auth_dep_mod
from context_service.api.auth_dep import get_auth_context
from context_service.auth.context import AuthContext
from context_service.config.settings import Settings


def _make_request() -> MagicMock:
    req = MagicMock()
    req.headers = {}
    return req


class TestDevBypass:
    async def test_returns_dev_auth_context_when_auth_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = Settings(
            _env_file=None,
            auth_enabled=False,
            dev_org_id="test-org",
            dev_user_id="test-user",
        )
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: settings)
        auth_dep_mod._dev_bypass_logged = False

        ctx = await get_auth_context(_make_request())

        assert isinstance(ctx, AuthContext)
        assert ctx.is_dev is True
        assert ctx.org_id == "test-org"
        assert ctx.user_id == "test-user"
        assert ctx.email is None

    async def test_dev_org_id_uses_settings_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        settings = Settings(
            _env_file=None,
            auth_enabled=False,
            dev_org_id="my-org",
            dev_user_id="my-user",
        )
        monkeypatch.setattr("context_service.api.auth_dep.get_settings", lambda: settings)
        auth_dep_mod._dev_bypass_logged = False

        ctx = await get_auth_context(_make_request())

        assert ctx.org_id == "my-org"
        assert ctx.user_id == "my-user"
