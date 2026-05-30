"""Unit tests for self-serve org provisioning helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from context_service.auth.org_provisioning import ensure_personal_org, resolve_workspace_name
from context_service.config.settings import Settings

_SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    auth_enabled=True,
    workos_api_key=SecretStr("test-key"),
    workos_client_id="test-client",
    workos_cookie_password=SecretStr("test-cookie-password-32-bytes-min!"),
)


def _not_found() -> Exception:
    """Construct a real WorkOS NotFoundError (6.0.8 ctor treats a non-str first
    arg as the response object)."""
    from workos import NotFoundError

    return NotFoundError(MagicMock(headers={}, status_code=404, response_dict={"code": "not_found"}))


def _conflict() -> Exception:
    """Construct a real WorkOS ConflictError (HTTP 409 duplicate external_id)."""
    from workos import ConflictError

    return ConflictError(MagicMock(headers={}, status_code=409, response_dict={"code": "conflict"}))


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
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
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
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
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

    def test_tolerates_already_a_member_conflict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2: an already-a-member ConflictError on the membership call is swallowed."""
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
        client = _make_client()
        found = MagicMock()
        found.id = "org-existing"
        client.organizations.get_organization_by_external_id.return_value = found
        client.user_management.create_organization_membership.side_effect = _conflict()

        with patch.dict(sys.modules, {"workos": _wrap(client)}):
            org_id = ensure_personal_org("wos-user-1", "Alice's workspace")  # must not raise

        assert org_id == "org-existing"

    def test_create_conflict_refetches_race_winner(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B3: a duplicate-external_id ConflictError on create -> re-fetch and reuse."""
        monkeypatch.setattr(
            "context_service.auth.org_provisioning.get_settings", lambda: _SETTINGS
        )
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
