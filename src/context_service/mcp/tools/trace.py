# src/context_service/mcp/tools/trace.py
"""MCP tool: trace - Explain why you believe something."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _trace_impl(node_id: str) -> dict[str, Any]:
    """Implementation for trace tool."""
    if not node_id:
        return {"error": "missing_node_id", "message": "node_id is required"}

    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "trace")
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()

    result = await ctx_svc.provenance(silo_id, node_id)

    return {
        "chain": [
            {
                "node_id": step.node_id,
                "layer": step.layer,
                "relationship": step.relationship,
                "confidence": step.confidence,
                "stub": step.stub,
            }
            for step in result.chain
        ],
        "root_sources": result.root_sources,
    }


def register(mcp: FastMCP) -> None:
    """Register the trace tool."""

    @mcp.tool(
        name="trace",
        description=get_tool_description("trace"),
    )
    @mcp_error_boundary
    async def trace(node_id: str) -> dict[str, Any]:
        """Trace provenance of a belief back to its sources.

        Args:
            node_id: Node to trace.

        Returns:
            {chain: [...], root_sources: [...]}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _trace_impl(node_id)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("trace", (time.perf_counter() - start) * 1000, success=success)
