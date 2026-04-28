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
