"""MCP tool: context_accept_belief - Accept a ProposedBelief and convert to Belief."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_accept_belief(
    proposed_belief_id: str,
    silo_id: str,
    confidence: float | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    if confidence is not None and not 0.0 <= confidence <= 1.0:
        return {"error": "invalid_confidence", "message": "confidence must be between 0.0 and 1.0"}

    store = get_context_service().graph_store
    belief_id = str(uuid.uuid4())
    accepted_at = datetime.now(UTC).isoformat()

    rows = await store.execute_write(
        q.ACCEPT_PROPOSED_BELIEF,
        {
            "proposed_belief_id": proposed_belief_id,
            "silo_id": silo_id,
            "belief_id": belief_id,
            "override_confidence": confidence,
            "accepted_at": accepted_at,
        },
    )

    if not rows:
        return {
            "error": "not_found",
            "message": f"ProposedBelief {proposed_belief_id!r} not found or not pending",
        }

    return {
        "proposed_belief_id": proposed_belief_id,
        "status": "accepted",
        "created_belief_id": rows[0]["belief_id"],
        "accepted_at": accepted_at,
    }


def register(mcp: FastMCP) -> None:
    """Register the context_accept_belief tool."""

    @mcp.tool(
        name="context_accept_belief",
        description=(
            "Accept a ProposedBelief and convert it to an active Belief. "
            "ProposedBeliefs are weak syntheses from the Custodian awaiting validation. "
            "Optionally override the confidence on acceptance."
        ),
    )
    async def context_accept_belief(
        belief_id: str,
        confidence: float | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Accept a ProposedBelief and promote it to Belief.

        Args:
            belief_id: ID of the ProposedBelief to accept.
            confidence: Optional confidence override (0.0-1.0). If not provided,
                uses the original confidence from the proposal.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {proposed_belief_id, status: "accepted", created_belief_id, accepted_at}
        """
        from context_service.mcp.server import get_mcp_auth_context, get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        start = time.perf_counter()
        result = await _context_accept_belief(
            proposed_belief_id=belief_id,
            silo_id=resolved_silo_id,
            confidence=confidence,
        )
        record_mcp_tool("context_accept_belief", (time.perf_counter() - start) * 1000)
        return result
