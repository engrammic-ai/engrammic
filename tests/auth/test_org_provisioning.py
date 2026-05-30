"""Unit tests for self-serve org provisioning helpers."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.org_provisioning import (
    ensure_personal_org,
    resolve_or_create_org,
    resolve_workspace_name,
)
from context_service.config.settings import Settings

_SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)


def _not_found() -> Exception:
    """Construct a real WorkOS NotFoundError. In 6.0.8 a non-str first arg is the
    response object (status/headers are read off it); ``code`` is passed explicitly."""
    from workos import NotFoundError

    return NotFoundError(MagicMock(headers={}, status_code=404), code="not_found")


def _conflict() -> Exception:
    """Construct a real WorkOS ConflictError (HTTP 409 duplicate external_id)."""
    from workos import ConflictError

    return ConflictError(MagicMock(headers={}, status_code=409), code="conflict")


def _unprocessable() -> Exception:
    """Construct a real WorkOS UnprocessableEntityError (HTTP 422); some WorkOS
    versions return this instead of 409 for an already-existing membership."""
    from workos import UnprocessableEntityError

    return UnprocessableEntityError(MagicMock(headers={}, status_code=422), code="unprocessable")


def _make_client() -> MagicMock:
    """A bare WorkOS client mock; tests wire specific side effects."""
    client = MagicMock()
    return client


def _wrap(client: MagicMock) -> MagicMock:
    from workos import ConflictError, NotFoundError, UnprocessableEntityError

    mod = MagicMock()
    mod.WorkOSClient.return_value = client
    mod.NotFoundError = NotFoundError
    mod.ConflictError = ConflictError
    mod.UnprocessableEntityError = UnprocessableEntityError
    return mod


class TestEnsurePersonalOrg:
    def test_creates_org_and_membership_when_none_exists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS)
        client = _make_client()
        client.organizations.get_organization_by_external_id.side_effect = _not_found()
        created = MagicMock()
        created.id = "org-new"
        client.organizations.create_organization.return_value = created

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-new"
        _, kwargs = client.organizations.create_organization.call_args
        assert kwargs["name"] == "Alice's workspace"
        assert kwargs["external_id"] == "wos-user-1"
        assert kwargs["metadata"] == {"source": "self-serve-signup"}
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-new"
        )

    def test_reuses_existing_org_and_repairs_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2: reuse path must (re)ensure membership, not assume it exists."""
        monkeypatch.setattr("context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS)
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-existing"
        client.organizations.create_organization.assert_not_called()
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-existing"
        )

    def test_tolerates_already_a_member_conflict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """B2: an already-a-member ConflictError on the membership call is swallowed."""
        monkeypatch.setattr("context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS)
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found
        client.user_management.create_organization_membership.side_effect = _conflict()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")  # must not raise

        assert org_id == "org-existing"

    def test_tolerates_unprocessable_entity_on_membership(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2: some WorkOS versions raise UnprocessableEntityError (not Conflict)
        for an already-existing membership; that must be swallowed too."""
        monkeypatch.setattr("context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS)
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found
        client.user_management.create_organization_membership.side_effect = _unprocessable()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")  # must not raise

        assert org_id == "org-existing"

    def test_create_conflict_refetches_race_winner(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """B3: a duplicate-external_id ConflictError on create -> re-fetch and reuse."""
        monkeypatch.setattr("context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS)
        client = _make_client()
        winner = MagicMock()
        winner.id = "org-winner"
        client.organizations.get_organization_by_external_id.side_effect = [
            _not_found(),
            winner,
        ]
        client.organizations.create_organization.side_effect = _conflict()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")

        assert org_id == "org-winner"
        client.user_management.create_organization_membership.assert_called_once_with(
            user_id="wos-user-1", organization_id="org-winner"
        )


class TestResolveWorkspaceName:
    def test_uses_full_name_when_present(self) -> None:
        assert resolve_workspace_name("Alice Example", "alice@x.com") == "Alice Example's workspace"

    def test_falls_back_to_email_local_part_when_name_missing(self) -> None:
        assert resolve_workspace_name(None, "alice@example.com") == "alice's workspace"

    def test_falls_back_when_name_is_blank(self) -> None:
        assert resolve_workspace_name("   ", "bob@example.com") == "bob's workspace"

    def test_strips_surrounding_whitespace_in_name(self) -> None:
        assert resolve_workspace_name("  Carol  ", "c@x.com") == "Carol's workspace"

    def test_neutral_default_when_no_name_and_no_local_part(self) -> None:
        assert resolve_workspace_name(None, "@example.com") == "New workspace"


class TestResolveOrCreateOrg:
    async def test_returns_session_org_id_without_db_or_workos(self) -> None:
        session = AsyncMock()
        with patch("context_service.auth.org_provisioning.ensure_personal_org") as ensure:
            result = await resolve_or_create_org(
                session,
                workos_user_id="wos-1",
                session_org_id="org-from-session",
                name="Alice",
                email="alice@x.com",
            )
        assert result == "org-from-session"
        ensure.assert_not_called()

    async def test_returns_stored_org_id_when_session_has_none(self) -> None:
        stored = MagicMock()
        stored.org_id = "org-stored"
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch("context_service.auth.org_provisioning.ensure_personal_org") as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=stored)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name="Alice", email="a@x.com"
            )
        assert result == "org-stored"
        ensure.assert_not_called()

    async def test_creates_when_no_session_and_no_stored_org(self) -> None:
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch(
                "context_service.auth.org_provisioning.ensure_personal_org",
                return_value="org-new",
            ) as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=None)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name=None, email="bob@x.com"
            )
        assert result == "org-new"
        ensure.assert_called_once_with("wos-1", "bob's workspace")

    async def test_creates_when_stored_org_is_legacy_userid_fallback(self) -> None:
        stored = MagicMock()
        stored.org_id = "wos-1"  # legacy fallback wrote org_id == workos_user_id
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch(
                "context_service.auth.org_provisioning.ensure_personal_org",
                return_value="org-new",
            ) as ensure,
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=stored)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name="Al", email="al@x.com"
            )
        assert result == "org-new"
        ensure.assert_called_once()

    async def test_legacy_upgrade_changes_derived_silo(self) -> None:
        """The legacy-fallback upgrade returns a real org whose derived silo
        differs from the old user-id-keyed silo (data-orphaning guard, finding #1)."""
        from context_service.services.models import derive_silo_id

        stored = MagicMock()
        stored.org_id = "wos-1"  # legacy fallback: org_id == workos_user_id
        session = AsyncMock()
        with (
            patch("context_service.auth.org_provisioning.UserService") as MockSvc,
            patch(
                "context_service.auth.org_provisioning.ensure_personal_org",
                return_value="org-new",
            ),
        ):
            MockSvc.return_value.get_user_by_workos_id = AsyncMock(return_value=stored)
            result = await resolve_or_create_org(
                session, workos_user_id="wos-1", session_org_id=None, name="Al", email="al@x.com"
            )
        assert result == "org-new"
        # The silo genuinely moves on upgrade - this is what strands old data.
        assert derive_silo_id(result) != derive_silo_id("wos-1")
