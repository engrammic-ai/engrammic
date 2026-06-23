"""Identity resolution for multi-agent coherence.

Resolves per-request identity (agent_id, session_id, model_id) through a
layered fallback chain. All writes must carry a non-null agent_id.

Fallback priority (highest to lowest):
  1. X-Agent-Id header (explicit caller identity)
  2. Resolved AuthContext.agent_id (set during OAuth/WorkOS auth)
  3. user_id from AuthContext (derived: "user:<user_id>")
  4. Silo-scoped anonymous sentinel ("anon-<sha256(silo_id+session_id)[:8]>")
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from context_service.auth.context import AuthContext


@dataclass(frozen=True, slots=True)
class IdentityContext:
    """Fully resolved identity for a single MCP request.

    All fields are guaranteed non-null. agent_id is always present because
    writes must be attributed. model_id is optional metadata only.
    """

    tenant_id: str
    agent_id: str
    session_id: str
    model_id: str | None = None


def resolve_identity(
    auth: AuthContext,
    *,
    explicit_agent_id: str | None = None,
    explicit_session_id: str | None = None,
    explicit_model_id: str | None = None,
) -> IdentityContext:
    """Resolve an IdentityContext from an authenticated request.

    Applies the fallback chain for each field:

    agent_id:
      1. explicit_agent_id (X-Agent-Id header)
      2. auth.agent_id (resolved during token verification)
      3. "user:<auth.user_id>" (derived from authenticated user)
      4. "anon-<fingerprint>" (deterministic last resort)

    session_id:
      1. explicit_session_id (X-Session-Id header)
      2. auth.session_id (set during token verification)
      3. "session-<fingerprint>" (deterministic from agent_id + tenant)

    model_id:
      1. explicit_model_id (X-Model-Id header)
      2. None (optional, not required)

    Args:
        auth: Resolved AuthContext for the current request.
        explicit_agent_id: Value from X-Agent-Id header, if present.
        explicit_session_id: Value from X-Session-Id header, if present.
        explicit_model_id: Value from X-Model-Id header, if present.

    Returns:
        IdentityContext with all required fields non-null.
    """
    from context_service.services.models import derive_silo_id

    tenant_id = str(derive_silo_id(auth.org_id))

    # Resolve agent_id through fallback chain
    agent_id = (
        explicit_agent_id
        or auth.agent_id
        or (f"user:{auth.user_id}" if auth.user_id else None)
        or _anon_fingerprint(tenant_id, auth.user_id)
    )

    # Resolve session_id through fallback chain
    session_id = (
        explicit_session_id
        or auth.session_id
        or _session_fingerprint(agent_id, tenant_id)
    )

    return IdentityContext(
        tenant_id=tenant_id,
        agent_id=agent_id,
        session_id=session_id,
        model_id=explicit_model_id,
    )


def _anon_fingerprint(tenant_id: str, user_id: str) -> str:
    """Deterministic anon sentinel scoped to tenant + user."""
    digest = hashlib.sha256(f"{tenant_id}:{user_id}".encode()).hexdigest()[:8]
    return f"anon-{digest}"


def _session_fingerprint(agent_id: str, tenant_id: str) -> str:
    """Deterministic session ID scoped to agent + tenant."""
    digest = hashlib.sha256(f"{tenant_id}:{agent_id}".encode()).hexdigest()[:12]
    return f"session-{digest}"
