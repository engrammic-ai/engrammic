# src/context_service/mcp/tools/forget.py
"""MCP tool: forget - Request deletion of a node."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.retention.forget_service import ForgetService
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Cypher query to find node IDs that directly reference the target node
_FIND_DOWNSTREAM_NODES = """
MATCH (other {silo_id: $silo_id})-[]->(n {id: $id, silo_id: $silo_id})
WHERE other.tombstoned_at IS NULL
RETURN other.id AS id
"""


async def _forget_impl(
    node_id: str,
    reason: str | None = None,
    cascade: bool = False,
) -> dict[str, Any]:
    """Implementation for forget tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "forget")
    silo_id = str(derive_silo_id(auth.org_id))

    ctx_svc = get_context_service()
    graph_store = ctx_svc.graph_store

    forget_svc = ForgetService(store=graph_store)
    result = await forget_svc.forget(node_id, silo_id, reason)

    # Invalidate cache on successful tombstone
    if result["status"] == "tombstoned":
        cache = getattr(ctx_svc, "_cache", None)
        if cache:
            await cache.delete(f"node:{silo_id}:{node_id}")

    if result["status"] != "tombstoned" or not cascade:
        return result

    # Cascade: find and forget downstream nodes (those referencing this node)
    downstream_rows = await graph_store.execute_query(
        _FIND_DOWNSTREAM_NODES,
        {"id": node_id, "silo_id": silo_id},
    )
    downstream_ids = [row["id"] for row in downstream_rows if row.get("id")]

    cascade_results: list[dict[str, Any]] = []
    cache = getattr(ctx_svc, "_cache", None)
    for downstream_id in downstream_ids:
        r = await forget_svc.forget(downstream_id, silo_id, reason)
        cascade_results.append(r)
        # Invalidate cache for cascade-forgotten nodes
        if r.get("status") == "tombstoned" and cache:
            await cache.delete(f"node:{silo_id}:{downstream_id}")

    result["cascade_forgotten"] = [
        r["node_id"] for r in cascade_results if r.get("status") == "tombstoned"
    ]
    return result


def register(mcp: FastMCP) -> None:
    """Register the forget tool."""

    @mcp.tool(
        name="forget",
        description=get_tool_description("forget"),
    )
    @mcp_error_boundary
    async def forget(
        node_id: str,
        reason: str | None = None,
        cascade: bool = False,
    ) -> dict[str, Any]:
        """Request deletion of a node.

        Args:
            node_id: ID of the node to forget.
            reason: Optional reason for the deletion (for audit).
            cascade: If True, also forget downstream nodes that reference this one.

        Returns:
            {status, node_id, tombstoned_at} or {status, node_id} on not_found.
            When cascade=True and status is tombstoned, also includes cascade_forgotten list.
        """
        start = time.perf_counter()
        success = True
        try:
            return await _forget_impl(node_id, reason, cascade)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("forget", (time.perf_counter() - start) * 1000, success=success)
