"""MCP tool: context_belief_history - Supersession chain timeline for a fact."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger(__name__)


async def _context_belief_history(
    silo_id: str,
    node_id: str,
    limit: int = 20,
) -> dict[str, Any]:
    """Internal implementation — testable without MCP transport."""
    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    ctx_svc = get_context_service()
    history = await ctx_svc.belief_history(
        silo_id=silo_id,
        node_id=node_id,
        limit=limit,
    )

    timeline = history.timeline
    first_belief = (
        timeline[0].valid_from.isoformat() if timeline and timeline[0].valid_from else None
    )
    last_change = (
        timeline[-1].valid_from.isoformat() if timeline and timeline[-1].valid_from else None
    )

    return {
        "subject": history.subject,
        "summary": {
            "total_versions": history.total_versions,
            "confidence_trend": history.confidence_trend,
            "first_belief": first_belief,
            "last_change": last_change,
        },
        "timeline": [
            {
                "node_id": s.node_id,
                "content": s.content,
                "confidence": s.confidence,
                "valid_from": s.valid_from.isoformat() if s.valid_from else None,
                "valid_to": s.valid_to.isoformat() if s.valid_to else None,
                "status": s.status,
                "superseded_by": s.superseded_by,
            }
            for s in timeline
        ],
    }


def register(mcp: FastMCP) -> None:
    """Register the context_belief_history tool."""

    @mcp.tool(
        name="context_belief_history",
        description=(
            "Retrieve the supersession chain for a fact node — "
            "shows how beliefs about a subject have evolved over time. "
            "Returns an ordered timeline with confidence trend analysis."
        ),
    )
    async def context_belief_history(
        node_id: str,
        limit: int = 20,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Get the belief evolution timeline for a fact.

        Args:
            node_id: Starting fact node ID. The tool traverses SUPERSEDES edges
                     in both directions to build the full chain.
            limit: Maximum nodes to return (default 20).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_belief_history(
            silo_id=resolved_silo_id, node_id=node_id, limit=limit
        )
