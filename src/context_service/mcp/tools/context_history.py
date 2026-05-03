"""MCP tool: context_history - Belief evolution over time via SUPERSEDES chain."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_history(
    silo_id: str,
    subject: str | None = None,
    node_id: str | None = None,
    include_confidence_trend: bool = False,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.server import (
        get_context_service,
        get_mcp_auth_context,
        get_silo_service,
    )
    from context_service.services.silo import validate_silo_ownership

    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not subject and not node_id:
        return {"error": "missing_input", "message": "Provide subject or node_id"}

    ctx_svc = get_context_service()
    result = await ctx_svc.history(
        silo_id=str(expected_silo_id),
        subject=subject,
        node_id=node_id,
    )

    timeline = [
        {
            "node_id": entry.node_id,
            "content": entry.content,
            "valid_from": entry.valid_from,
            "valid_to": entry.valid_to,
            "confidence": entry.confidence,
            "supersession_reason": entry.supersession_reason,
        }
        for entry in result.timeline
    ]

    out: dict[str, Any] = {
        "timeline": timeline,
        "current": result.current,
        "entries_count": len(timeline),
    }

    if include_confidence_trend and node_id:
        belief = await ctx_svc.belief_history(
            silo_id=str(expected_silo_id),
            node_id=node_id,
        )
        belief_timeline = belief.timeline
        first_belief = (
            belief_timeline[0].valid_from.isoformat()
            if belief_timeline and belief_timeline[0].valid_from
            else None
        )
        last_change = (
            belief_timeline[-1].valid_from.isoformat()
            if belief_timeline and belief_timeline[-1].valid_from
            else None
        )
        out["confidence_trend"] = belief.confidence_trend
        out["first_belief"] = first_belief
        out["last_change"] = last_change
        out["belief_timeline"] = [
            {
                "node_id": s.node_id,
                "content": s.content,
                "confidence": s.confidence,
                "valid_from": s.valid_from.isoformat() if s.valid_from else None,
                "valid_to": s.valid_to.isoformat() if s.valid_to else None,
                "status": s.status,
                "superseded_by": s.superseded_by,
            }
            for s in belief_timeline
        ]

    return out


def register(mcp: FastMCP) -> None:
    """Register the context_history tool."""

    @mcp.tool(
        name="context_history",
        description=(
            "Show how a belief or fact evolved over time. "
            "Traverses the SUPERSEDES chain from oldest to newest. "
            "Accepts either a node_id (specific node) or subject (keyword search). "
            "Set include_confidence_trend=true with a node_id to also return the "
            "full confidence trend analysis and belief timeline."
        ),
    )
    async def context_history(
        subject: str | None = None,
        node_id: str | None = None,
        silo_id: str | None = None,
        include_confidence_trend: bool = False,
    ) -> dict[str, Any]:
        """Show belief evolution over time.

        Args:
            subject: Keyword to search for in content/subject field.
            node_id: Specific node to trace history for.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            include_confidence_trend: When True and node_id is provided, include
                confidence_trend and belief_timeline in the response.

        Returns:
            {timeline, current, entries_count} and optionally {confidence_trend, belief_timeline}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_history(
            silo_id=resolved_silo_id,
            subject=subject,
            node_id=node_id,
            include_confidence_trend=include_confidence_trend,
        )
