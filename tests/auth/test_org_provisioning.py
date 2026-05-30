"""Unit tests for self-serve org provisioning helpers."""

from __future__ import annotations

from context_service.auth.org_provisioning import resolve_workspace_name


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
