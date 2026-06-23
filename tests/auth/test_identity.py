"""Tests for identity resolution fallback chain."""

from __future__ import annotations

from context_service.auth.context import AuthContext
from context_service.auth.identity import IdentityContext, resolve_identity


def _auth(
    org_id: str = "org-1",
    user_id: str = "user-abc",
    agent_id: str | None = None,
    session_id: str | None = None,
) -> AuthContext:
    return AuthContext(
        org_id=org_id,
        user_id=user_id,
        email=None,
        is_dev=False,
        agent_id=agent_id,
        session_id=session_id,
    )


class TestResolveIdentity:
    def test_returns_identity_context(self) -> None:
        ctx = resolve_identity(_auth())
        assert isinstance(ctx, IdentityContext)

    def test_tenant_id_derived_from_org_id(self) -> None:
        from context_service.services.models import derive_silo_id

        auth = _auth(org_id="org-xyz")
        ctx = resolve_identity(auth)
        assert ctx.tenant_id == str(derive_silo_id("org-xyz"))

    def test_agent_id_explicit_has_highest_priority(self) -> None:
        auth = _auth(agent_id="from-auth")
        ctx = resolve_identity(auth, explicit_agent_id="explicit-agent")
        assert ctx.agent_id == "explicit-agent"

    def test_agent_id_falls_back_to_auth_agent_id(self) -> None:
        auth = _auth(agent_id="from-auth")
        ctx = resolve_identity(auth)
        assert ctx.agent_id == "from-auth"

    def test_agent_id_falls_back_to_user_prefix(self) -> None:
        auth = _auth(user_id="user-123", agent_id=None)
        ctx = resolve_identity(auth)
        assert ctx.agent_id == "user:user-123"

    def test_session_id_explicit_has_highest_priority(self) -> None:
        auth = _auth(session_id="from-auth")
        ctx = resolve_identity(auth, explicit_session_id="explicit-session")
        assert ctx.session_id == "explicit-session"

    def test_session_id_falls_back_to_auth_session_id(self) -> None:
        auth = _auth(session_id="auth-session-42")
        ctx = resolve_identity(auth)
        assert ctx.session_id == "auth-session-42"

    def test_session_id_synthesized_when_missing(self) -> None:
        auth = _auth(session_id=None)
        ctx = resolve_identity(auth)
        assert ctx.session_id.startswith("session-")
        assert len(ctx.session_id) > len("session-")

    def test_session_id_synthesized_is_deterministic(self) -> None:
        auth = _auth(session_id=None)
        ctx1 = resolve_identity(auth)
        ctx2 = resolve_identity(auth)
        assert ctx1.session_id == ctx2.session_id

    def test_model_id_explicit(self) -> None:
        auth = _auth()
        ctx = resolve_identity(auth, explicit_model_id="claude-sonnet-4-6")
        assert ctx.model_id == "claude-sonnet-4-6"

    def test_model_id_defaults_none(self) -> None:
        auth = _auth()
        ctx = resolve_identity(auth)
        assert ctx.model_id is None

    def test_agent_id_never_null(self) -> None:
        auth = _auth(agent_id=None, user_id="u1")
        ctx = resolve_identity(auth)
        assert ctx.agent_id is not None
        assert ctx.agent_id != ""

    def test_identity_context_is_frozen(self) -> None:
        import pytest

        auth = _auth()
        ctx = resolve_identity(auth)
        with pytest.raises((AttributeError, TypeError)):
            ctx.agent_id = "changed"  # type: ignore[misc]

    def test_different_agents_get_different_fingerprints(self) -> None:
        auth_a = _auth(user_id="user-a", agent_id=None, session_id=None)
        auth_b = _auth(user_id="user-b", agent_id=None, session_id=None)
        ctx_a = resolve_identity(auth_a)
        ctx_b = resolve_identity(auth_b)
        assert ctx_a.agent_id != ctx_b.agent_id
