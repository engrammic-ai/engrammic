# src/context_service/mcp/tools/history.py
"""MCP tool: history - Show how a belief evolved over time."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


def _format_timestamp(ts: Any) -> str | None:
    """Format a timestamp value to an ISO 8601 string."""
    if ts is None:
        return None
    if hasattr(ts, "isoformat"):
        return str(ts.isoformat())
    return str(ts)


@rate_limited("history")
async def _history_impl(node_id: str) -> dict[str, Any]:
    """Implementation for history tool."""
    if not node_id:
        return {"error": "missing_node_id", "message": "node_id is required"}

    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "history")
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()

    try:
        result = await ctx_svc.history(silo_id, node_id=node_id)
    except Exception as e:
        error_msg = str(e).lower()
        if "not found" in error_msg or "no node" in error_msg:
            return {"error": "not_found", "node_id": node_id}
        raise

    if not result.timeline:
        return {"error": "not_found", "node_id": node_id}

    timeline = []
    for i, entry in enumerate(result.timeline):
        item: dict[str, Any] = {
            "node_id": entry.node_id,
            "content": entry.content,
            "valid_from": _format_timestamp(entry.valid_from),
            "valid_to": _format_timestamp(entry.valid_to),
            "confidence": entry.confidence,
        }
        # Omit supersession_reason on root node (first entry)
        if i > 0 and entry.supersession_reason is not None:
            item["supersession_reason"] = entry.supersession_reason
        timeline.append(item)

    return {"timeline": timeline}


def register(mcp: FastMCP) -> None:
    """Register the history tool."""

    @mcp.tool(
        name="history",
        description=get_tool_description("history"),
    )
    @mcp_error_boundary
    async def history(node_id: str) -> dict[str, Any]:
        """Show how a belief evolved over time.

        Returns the supersession chain from oldest to newest. Use when you need
        to understand how knowledge changed, not just what it is now.

        Args:
            node_id: Start from this node, walk SUPERSEDES chain.

        Returns:
            {timeline: [...]}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _history_impl(node_id)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("history", (time.perf_counter() - start) * 1000, success=success)
