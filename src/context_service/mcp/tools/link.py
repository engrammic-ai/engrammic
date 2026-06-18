# src/context_service/mcp/tools/link.py
"""MCP tool: link - Create a relationship between nodes.

DEPRECATED (CITE v2): Explicit link creation folded into remember/learn.
The v2 edge set (DERIVED_FROM, SUPERSEDES, SUPPORTS, CONTRADICTS, ABOUT) is
managed by SAGE and the supersedes param. This tool is kept for backward
compatibility only.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.context_link import _context_link
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("link")
async def _link_impl(
    from_node: str,
    to_node: str,
    relationship: str,
    weight: float = 1.0,
    note: str | None = None,
) -> dict[str, Any]:
    """Implementation for link tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "link")
    silo_id = str(derive_silo_id(auth.org_id))
    return await _context_link(
        silo_id=silo_id,
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
    @mcp_error_boundary
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
            relationship: Type (CITE v2): DERIVED_FROM|SYNTHESIZED_FROM|SUPERSEDES|SUPPORTS|CONTRADICTS|ABOUT.
                Legacy types (REFERENCES, CORROBORATES, CAUSES, PREVENTS, RELATED_TO) accepted
                but mapped to v2 equivalents or ignored.
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
