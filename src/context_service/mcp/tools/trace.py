# src/context_service/mcp/tools/trace.py
"""MCP tool: trace - Explain why you believe something."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

VALID_EDGE_TYPES = frozenset({"DERIVED_FROM", "PROMOTED_FROM", "SYNTHESIZED_FROM", "REFERENCES"})


@rate_limited("trace")
async def _trace_impl(
    node_id: str,
    direction: Literal["up", "down"] = "up",
    max_depth: int = 5,
    edge_types: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for trace tool."""
    if not node_id:
        return {"error": "missing_node_id", "message": "node_id is required"}

    if edge_types:
        invalid = set(edge_types) - VALID_EDGE_TYPES
        if invalid:
            return {
                "error": "invalid_edge_types",
                "message": f"Invalid edge types: {invalid}",
                "valid": list(VALID_EDGE_TYPES),
            }

    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "trace")
    silo_id = str(derive_silo_id(auth.org_id))
    ctx_svc = get_context_service()

    result = await ctx_svc.provenance(
        silo_id,
        node_id,
        max_depth=max_depth,
        direction=direction,
        edge_types=edge_types,
    )

    response: dict[str, Any] = {
        "direction": direction,
        "max_depth": max_depth,
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
    }

    if direction == "up":
        response["root_sources"] = result.root_sources
    else:
        response["leaf_nodes"] = result.root_sources

    return response


def register(mcp: FastMCP) -> None:
    """Register the trace tool."""

    @mcp.tool(
        name="trace",
        description=get_tool_description("trace"),
    )
    @mcp_error_boundary
    async def trace(
        node_id: str,
        direction: Literal["up", "down"] = "up",
        max_depth: int = 5,
        edge_types: list[str] | None = None,
    ) -> dict[str, Any]:
        """Trace provenance or impact of a node.

        Args:
            node_id: Node to trace.
            direction: "up" traces to sources (why I believe this),
                "down" traces to derived nodes (what depends on this).
            max_depth: Maximum traversal depth (default 5).
            edge_types: Filter to specific edge types. Valid values:
                DERIVED_FROM, PROMOTED_FROM, SYNTHESIZED_FROM, REFERENCES.

        Returns:
            {direction, max_depth, chain: [...], root_sources|leaf_nodes: [...]}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _trace_impl(node_id, direction, max_depth, edge_types)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("trace", (time.perf_counter() - start) * 1000, success=success)
