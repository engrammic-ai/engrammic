"""Integration tests for auth + user sync flow."""

from __future__ import annotations

import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.context import AuthContext
from context_service.auth.workos_client import verify_session
from context_service.config.settings import Settings

_WORKOS_SETTINGS = Settings(
    _env_file=None,
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)

_WORKOS_USER = {
    "id": "wos-user-abc123",
    "email": "alice@example.com",
    "first_name": "Alice",
    "last_name": "Example",
}

_ORG_ID = "org-xyz-789"


def _make_workos_response(authenticated: bool = True) -> MagicMock:
    """Return a minimal WorkOS authenticate_with_session_cookie response."""
    resp = MagicMock()
    resp.authenticated = authenticated
    resp.user = _WORKOS_USER if authenticated else None
    resp.organization_id = _ORG_ID if authenticated else None
    resp.reason = "not_authenticated"
    return resp


def _make_workos_module(response: Any) -> MagicMock:
    """Build a minimal fake `workos` module."""
    client = MagicMock()
    client.user_management.authenticate_with_session_cookie.return_value = response

    workos_mod = MagicMock()
    workos_mod.WorkOSClient.return_value = client
    return workos_mod


def _make_fake_db_user() -> MagicMock:
    """Return a fake User ORM object with an id."""
    fake_user = MagicMock()
    fake_user.id = uuid.uuid4()
    return fake_user


@asynccontextmanager
async def _fake_get_session(session_mock: Any):  # type: ignore[return]
    yield session_mock


@pytest.mark.integration
class TestAuthUserSync:
    """Tests for user sync during WorkOS auth."""

    async def test_verify_session_upserts_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """verify_session should call upsert_user with the correct WorkOS user fields."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        fake_db_user = _make_fake_db_user()
        session_mock = AsyncMock()
        upsert_mock = AsyncMock(return_value=fake_db_user)

        workos_response = _make_workos_response()
        fake_workos = _make_workos_module(workos_response)

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_get_session(session_mock),
            ),
            patch(
                "context_service.services.user.UserService",
            ) as MockUserService,
        ):
            MockUserService.return_value.upsert_user = upsert_mock
            await verify_session("sealed-token-abc")

        upsert_mock.assert_awaited_once()
        call_kwargs = upsert_mock.call_args
        assert call_kwargs.kwargs["workos_user_id"] == _WORKOS_USER["id"]
        assert call_kwargs.kwargs["email"] == _WORKOS_USER["email"]
        assert call_kwargs.kwargs["org_id"] == _ORG_ID
        assert call_kwargs.kwargs["name"] == "Alice Example"

    async def test_verify_session_returns_db_user_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AuthContext should have db_user_id populated from the upserted User row."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        fake_db_user = _make_fake_db_user()
        session_mock = AsyncMock()
        upsert_mock = AsyncMock(return_value=fake_db_user)

        workos_response = _make_workos_response()
        fake_workos = _make_workos_module(workos_response)

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_get_session(session_mock),
            ),
            patch(
                "context_service.services.user.UserService",
            ) as MockUserService,
        ):
            MockUserService.return_value.upsert_user = upsert_mock
            ctx = await verify_session("sealed-token-abc")

        assert isinstance(ctx, AuthContext)
        assert ctx.db_user_id == fake_db_user.id
        assert ctx.user_id == _WORKOS_USER["id"]
        assert ctx.org_id == _ORG_ID
        assert ctx.email == _WORKOS_USER["email"]

    async def test_verify_session_calls_upsert_on_each_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each verify_session call should invoke upsert_user, refreshing last_active_at."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        fake_db_user = _make_fake_db_user()
        upsert_mock = AsyncMock(return_value=fake_db_user)

        workos_response = _make_workos_response()
        fake_workos = _make_workos_module(workos_response)

        def _get_session_factory():
            return _fake_get_session(AsyncMock())

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                side_effect=_get_session_factory,
            ),
            patch(
                "context_service.services.user.UserService",
            ) as MockUserService,
        ):
            MockUserService.return_value.upsert_user = upsert_mock

            await verify_session("sealed-token-first")
            await verify_session("sealed-token-second")

        assert upsert_mock.await_count == 2

    async def test_verify_session_fail_open_on_postgres_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Auth should succeed with db_user_id=None when Postgres is unavailable."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        workos_response = _make_workos_response()
        fake_workos = _make_workos_module(workos_response)

        @asynccontextmanager
        async def _failing_get_session():  # type: ignore[return]
            raise OSError("Connection refused: Postgres unavailable")
            yield  # pragma: no cover

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_failing_get_session(),
            ),
        ):
            ctx = await verify_session("sealed-token-abc")

        assert isinstance(ctx, AuthContext)
        assert ctx.db_user_id is None
        # WorkOS auth fields are still populated
        assert ctx.user_id == _WORKOS_USER["id"]
        assert ctx.org_id == _ORG_ID
        assert ctx.email == _WORKOS_USER["email"]
        assert ctx.is_dev is False

    async def test_verify_session_provisions_org_when_session_has_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No-org sealed session should provision an org, not raise."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        fake_db_user = _make_fake_db_user()
        session_mock = AsyncMock()
        upsert_mock = AsyncMock(return_value=fake_db_user)

        # session response WITHOUT an organization_id
        no_org_response = _make_workos_response()
        no_org_response.organization_id = None
        fake_workos = _make_workos_module(no_org_response)

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_fake_get_session(session_mock),
            ),
            patch(
                "context_service.services.user.UserService",
            ) as MockUserService,
            patch(
                "context_service.auth.workos_client.resolve_or_create_org",
                AsyncMock(return_value="org-provisioned"),
            ) as resolve_mock,
        ):
            MockUserService.return_value.upsert_user = upsert_mock
            ctx = await verify_session("sealed-token-no-org")

        resolve_mock.assert_awaited_once()
        assert ctx.org_id == "org-provisioned"
        assert upsert_mock.await_args.kwargs["org_id"] == "org-provisioned"

    async def test_verify_session_fails_closed_when_no_org_and_db_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A genuinely-new no-org user that cannot be provisioned (DB down) must
        fail CLOSED: no valid silo can be derived from a None org id."""
        monkeypatch.setattr(
            "context_service.auth.workos_client.get_settings", lambda: _WORKOS_SETTINGS
        )

        # no organization_id on the session, and the DB session is unavailable
        no_org_response = _make_workos_response()
        no_org_response.organization_id = None
        fake_workos = _make_workos_module(no_org_response)

        @asynccontextmanager
        async def _failing_get_session():  # type: ignore[return]
            raise OSError("Connection refused: Postgres unavailable")
            yield  # pragma: no cover

        with (
            patch.dict(sys.modules, {"workos": fake_workos}),
            patch(
                "context_service.db.postgres.get_session",
                return_value=_failing_get_session(),
            ),pytest.raises(ValueError, match="organization")
        ):
            await verify_session("sealed-token-no-org-db-down")
