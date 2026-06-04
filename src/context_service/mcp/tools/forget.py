# src/context_service/mcp/tools/forget.py
"""MCP tool: forget - Request deletion of a node."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.server import get_context_service, get_mcp_auth_context, track_tool_usage
from context_service.mcp.tools.registry import get_tool_description
from context_service.reactions.events import emit_reaction
from context_service.sage.transactions import InvariantViolation
from context_service.sage.transactions import forget as brain_forget
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _forget_impl(
    node_id: str,
    reason: str | None = None,
    cascade: bool = False,
) -> dict[str, Any]:
    """Implementation for forget tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "forget")
    silo_id = str(derive_silo_id(auth.org_id))
    agent_id = auth.agent_id or auth.org_id

    ctx_svc = get_context_service()

    try:
        result, events = await brain_forget(
            store=ctx_svc.graph_store,
            node_id=node_id,
            silo_id=silo_id,
            agent_id=agent_id,
            reason=reason,
            cascade=cascade,
        )
    except InvariantViolation as exc:
        if exc.code == "NODE_NOT_FOUND":
            return {"status": "not_found", "node_id": node_id}
        if exc.code in ("ALREADY_TOMBSTONED", "ALREADY_DELETED"):
            return {"status": "not_found", "node_id": node_id}
        return {"error": exc.code, "message": exc.message, "node_id": node_id}

    for event in events:
        await emit_reaction(event)

    # Invalidate cache on successful tombstone
    cache = getattr(ctx_svc, "_cache", None)
    if cache:
        await cache.delete(f"node:{silo_id}:{node_id}")

    response: dict[str, Any] = {
        "status": "tombstoned",
        "node_id": str(result.node_id),
        "tombstoned_at": result.tombstoned_at.isoformat(),
    }
    if cascade and result.cascade_count:
        response["cascade_count"] = result.cascade_count
    return response


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
