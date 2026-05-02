"""MCP tool: context_belief_history - Supersession chain timeline for a fact."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.engine.history import get_belief_history
from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
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
    history = await get_belief_history(
        memgraph=ctx_svc._memgraph,
        silo_id=silo_id,
        start_id=node_id,
        limit=limit,
    )

    return {
        "subject": history.subject,
        "total_versions": history.total_versions,
        "confidence_trend": history.confidence_trend,
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
            for s in history.timeline
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
        silo_id: str,
        node_id: str,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get the belief evolution timeline for a fact.

        Args:
            silo_id: The silo to search within.
            node_id: Starting fact node ID. The tool traverses SUPERSEDES edges
                     in both directions to build the full chain.
            limit: Maximum nodes to return (default 20).
        """
        return await _context_belief_history(silo_id=silo_id, node_id=node_id, limit=limit)
