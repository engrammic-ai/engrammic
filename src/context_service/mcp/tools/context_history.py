"""MCP tool: context_history - Belief evolution over time via SUPERSEDES chain."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_history(
    silo_id: str,
    subject: str | None = None,
    node_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.auth import get_mcp_auth

    auth = get_mcp_auth()
    expected_silo_id = derive_silo_id(auth.org_id)

    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    if not subject and not node_id:
        return {"error": "missing_input", "message": "Provide subject or node_id"}

    from context_service.mcp.server import get_context_service

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

    return {
        "timeline": timeline,
        "current": result.current,
        "entries_count": len(timeline),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_history tool."""

    @mcp.tool(
        name="context_history",
        description=(
            "Show how a belief or fact evolved over time. "
            "Traverses the SUPERSEDES chain from oldest to newest. "
            "Accepts either a node_id (specific node) or subject (keyword search)."
        ),
    )
    async def context_history(
        silo_id: str,
        subject: str | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        """Show belief evolution over time.

        Args:
            silo_id: UUID of the silo.
            subject: Keyword to search for in content/subject field.
            node_id: Specific node to trace history for.

        Returns:
            {timeline, current, entries_count}
        """
        return await _context_history(
            silo_id=silo_id,
            subject=subject,
            node_id=node_id,
        )
