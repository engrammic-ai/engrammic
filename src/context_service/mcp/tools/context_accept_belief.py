"""MCP tool: context_accept_belief - Accept a ProposedBelief and create a WorkingBelief."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_accept_belief(
    proposal_id: str,
    silo_id: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    store = get_context_service().graph_store
    now = datetime.now(UTC).isoformat()

    # Update the ProposedBelief status to "accepted"
    rows = await store.execute_write(
        q.UPDATE_PROPOSED_BELIEF_STATUS,
        {"id": proposal_id, "silo_id": silo_id, "status": "accepted"},
    )

    if not rows:
        return {
            "error": "not_found",
            "message": f"ProposedBelief {proposal_id!r} not found in silo",
        }

    proposal = rows[0].get("pb") if rows else None
    if proposal is None:
        return {
            "error": "not_found",
            "message": f"ProposedBelief {proposal_id!r} not found in silo",
        }

    content = proposal.get("content", "")
    confidence = proposal.get("confidence", 0.5)
    pb_session_id = session_id or proposal.get("session_id")

    if not pb_session_id:
        return {
            "error": "missing_session_id",
            "message": "session_id is required to create a WorkingBelief (provide it or ensure the ProposedBelief has one)",
        }

    # Create a WorkingBelief from the proposal content
    working_belief_id = str(uuid.uuid4())
    wb_rows = await store.execute_write(
        q.CREATE_WORKING_BELIEF,
        {
            "id": working_belief_id,
            "silo_id": silo_id,
            "session_id": pb_session_id,
            "content": content,
            "confidence": confidence,
            "created_at": now,
            "about_ids": [],
        },
    )

    if not wb_rows:
        return {
            "error": "working_belief_creation_failed",
            "message": "ProposedBelief accepted but WorkingBelief creation failed (session may not exist)",
            "proposal_id": proposal_id,
        }

    return {
        "proposal_id": proposal_id,
        "status": "accepted",
        "working_belief_id": working_belief_id,
        "session_id": pb_session_id,
        "accepted_at": now,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_accept_belief tool."""

    @mcp.tool(
        name="context_accept_belief",
        description=(
            "Accept a ProposedBelief: marks it as accepted and creates a WorkingBelief "
            "from its content so the agent can reason with it in the current session."
        ),
    )
    async def context_accept_belief(
        proposal_id: str,
        silo_id: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Accept a ProposedBelief and promote it to a WorkingBelief.

        Args:
            proposal_id: ID of the ProposedBelief to accept.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            session_id: ReasoningSession to attach the new WorkingBelief to.
                Optional; falls back to the session recorded on the ProposedBelief.

        Returns:
            {proposal_id, status, working_belief_id, session_id, accepted_at}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        resolved_session_id = session_id or auth.session_id
        return await _context_accept_belief(
            proposal_id=proposal_id,
            silo_id=resolved_silo_id,
            session_id=resolved_session_id,
        )
