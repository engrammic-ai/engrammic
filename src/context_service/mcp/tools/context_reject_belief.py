"""MCP tool: context_reject_belief - Reject a ProposedBelief."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.errors import error_response, success_response
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_reject_belief(
    proposal_id: str,
    silo_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    store = get_context_service().graph_store
    now = datetime.now(UTC).isoformat()

    # Update the ProposedBelief status to "rejected"
    rows = await store.execute_write(
        q.UPDATE_PROPOSED_BELIEF_STATUS,
        {"id": proposal_id, "silo_id": silo_id, "status": "rejected"},
    )

    if not rows:
        return error_response(
            "NOT_FOUND",
            f"ProposedBelief {proposal_id!r} not found in silo",
            details={"proposal_id": proposal_id, "silo_id": silo_id},
        )

    # If a rejection reason was provided, store it on the node
    if reason:
        await store.execute_write(
            q.UPDATE_PROPOSED_BELIEF_REJECTION,
            {"id": proposal_id, "silo_id": silo_id, "reason": reason, "rejected_at": now},
        )

    data: dict[str, Any] = {
        "proposal_id": proposal_id,
        "status": "rejected",
        "rejected_at": now,
    }
    if reason:
        data["reason"] = reason
    return success_response(data)


def register(mcp: FastMCP) -> None:
    """Register the context_reject_belief tool."""

    @mcp.tool(
        name="context_reject_belief",
        description=(
            "Reject a ProposedBelief: marks it as rejected and optionally records "
            "a reason. Rejected beliefs are not promoted to WorkingBeliefs."
        ),
    )
    async def context_reject_belief(
        proposal_id: str,
        silo_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Reject a ProposedBelief.

        Args:
            proposal_id: ID of the ProposedBelief to reject.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            reason: Optional human-readable explanation for the rejection.
                Stored on the ProposedBelief node as rejection_reason.

        Returns:
            {proposal_id, status, rejected_at, reason?}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_reject_belief(
            proposal_id=proposal_id,
            silo_id=resolved_silo_id,
            reason=reason,
        )
