# src/context_service/mcp/tools/accept.py
"""MCP tool: accept - Accept a ProposedBelief, promoting it to Belief."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation, accept_proposal
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("accept")
async def _accept_impl(
    proposal_id: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Implementation for accept tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "accept")

    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()
    agent_id = auth.agent_id or auth.org_id

    try:
        result, events = await accept_proposal(
            store=ctx_svc.graph_store,
            proposal_id=proposal_id,
            silo_id=silo_id,
            agent_id=agent_id,
            reason=reason,
            emit=False,
        )

        for event in events:
            await emit_reaction(event)

        return {
            "belief_id": str(result.belief_id),
            "proposal_id": str(result.proposal_id),
            "accepted": result.accepted,
            "accepted_at": result.accepted_at.isoformat(),
            "confidence": result.confidence,
        }

    except InvariantViolation as e:
        return {
            "error": e.code,
            "message": e.message,
        }


def register(mcp: FastMCP) -> None:
    """Register the accept tool."""

    @mcp.tool(
        name="accept",
        description=get_tool_description("accept"),
    )
    @mcp_error_boundary
    async def accept(
        proposal_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Accept a ProposedBelief, promoting it to a full Belief.

        ProposedBeliefs are created by SAGE synthesis. Use accept to confirm
        you agree with the synthesized belief. Use dismiss to reject it.

        Args:
            proposal_id: The ProposedBelief node ID.
            reason: Optional rationale for acceptance.

        Returns:
            {belief_id, proposal_id, accepted, accepted_at, confidence}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _accept_impl(proposal_id, reason)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("accept", (time.perf_counter() - start) * 1000, success=success)
