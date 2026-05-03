"""MCP tool: context_reason - Store reasoning chains to Intelligence layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.models.mcp import Crystallization, ReasoningStep
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_reason(
    silo_id: str,
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
    crystallizations: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.engine.sessions import attach_chain_to_session, create_or_join_session
    from context_service.mcp.server import (
        get_context_service,
        get_mcp_auth_context,
        get_silo_service,
    )

    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not steps:
        return {"error": "missing_steps", "message": "steps must be a non-empty list"}

    try:
        parsed_steps = [ReasoningStep(**s) for s in steps]
    except Exception as e:
        return {"error": "invalid_steps", "message": str(e)}

    try:
        parsed_cryst = [Crystallization(**c) for c in (crystallizations or [])]
    except Exception as e:
        return {"error": "invalid_crystallizations", "message": str(e)}

    ctx_svc = get_context_service()

    # session_id: caller-provided takes precedence; fall back to auth session, then new uuid.
    resolved_session_id = (
        session_id
        or getattr(auth, "session_id", None)
        or str(uuid.uuid4())
    )
    agent_id = getattr(auth, "agent_id", None)

    # Upsert the session node before writing the chain.
    store = ctx_svc.graph_store
    await create_or_join_session(store, resolved_session_id, str(expected_silo_id))

    result = await ctx_svc.reason(
        silo_id=str(expected_silo_id),
        steps=parsed_steps,
        conclusion=conclusion,
        evidence_used=evidence_used,
        crystallizations=parsed_cryst,
        session_id=resolved_session_id,
        agent_id=agent_id,
    )

    # Attach the new chain to the session.
    await attach_chain_to_session(
        store, str(result.chain_id), resolved_session_id, str(expected_silo_id)
    )

    return {
        "chain_id": str(result.chain_id),
        "layer": "intelligence",
        "steps_count": len(steps),
        "crystallizations_queued": len(parsed_cryst),
        "session_id": resolved_session_id,
        "created_at": datetime.now(UTC).isoformat(),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_reason tool."""

    @mcp.tool(
        name="context_reason",
        description=(
            "Store a multi-step reasoning chain to the Intelligence layer. "
            "Optionally extract crystallizations (beliefs or claims) from the chain. "
            "Use to persist agent deliberation for audit, reflection, and learning."
        ),
    )
    async def context_reason(
        steps: list[dict[str, Any]],
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
        crystallizations: list[dict[str, Any]] | None = None,
        session_id: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Store reasoning chain to Intelligence layer.

        Args:
            steps: List of {step, reasoning, confidence?} dicts.
            conclusion: Optional summary conclusion.
            evidence_used: Optional list of node:<uuid> or URI refs used.
            crystallizations: Optional list of {claim, confidence?} to extract.
            session_id: Optional session UUID to group multiple chains together.
                        If omitted a new session is created automatically.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {chain_id, layer, steps_count, crystallizations_queued, session_id, created_at}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_reason(
            silo_id=resolved_silo_id,
            steps=steps,
            conclusion=conclusion,
            evidence_used=evidence_used,
            crystallizations=crystallizations,
            session_id=session_id,
        )
