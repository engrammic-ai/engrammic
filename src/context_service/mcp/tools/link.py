# src/context_service/mcp/tools/link.py
"""MCP tool: link - Create a relationship between nodes."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_link import _context_link
from context_service.mcp.tools.registry import get_tool_description
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _link_impl(
    from_node: str,
    to_node: str,
    relationship: str,
    weight: float = 1.0,
    note: str | None = None,
) -> dict[str, Any]:
    """Implementation for link tool."""
    return await _context_link(
        silo_id=None,
        from_node=from_node,
        to_node=to_node,
        relationship=relationship,
        weight=weight,
        note=note,
    )


def register(mcp: FastMCP) -> None:
    """Register the link tool."""

    @mcp.tool(
        name="link",
        description=get_tool_description("link"),
    )
    async def link(
        from_node: str,
        to_node: str,
        relationship: str,
        weight: float = 1.0,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Create a typed relationship between nodes.

        Args:
            from_node: Source node ID.
            to_node: Target node ID.
            relationship: Type: supports|contradicts|derives|references|causes|supersedes.
            weight: Strength 0.0-10.0 (default 1.0).
            note: Optional annotation.

        Returns:
            {edge_id, created_at}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _link_impl(from_node, to_node, relationship, weight, note)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("link", (time.perf_counter() - start) * 1000, success=success)
