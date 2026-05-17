# src/context_service/mcp/tools/recall.py
"""MCP tool: recall - Search or fetch knowledge."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_mcp_auth_context, get_preset_resolver
from context_service.mcp.tools.context_recall import _context_recall
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))

    effective_top_k = top_k
    if effective_top_k is None:
        effective_top_k = 10
        try:
            preset = await get_preset_resolver().resolve(silo_id)
            override = preset.param_overrides.get("default_recall_top_k")
            if (
                isinstance(override, int)
                and not isinstance(override, bool)
                and override > 0
            ):
                effective_top_k = override
        except RuntimeError:
            pass

    result = await _context_recall(
        silo_id=silo_id,
        query=query,
        node_ids=node_ids,
        depth=depth,
        layers=layers,
        top_k=effective_top_k,
    )

    # Track node access for evidence accessibility (Layer 3 chain reuse)
    session_id = auth.session_id
    if session_id and result.get("results"):
        await _track_node_access(silo_id, session_id, result["results"])

    if include_hypotheses:
        # Fetch active hypotheses for current session
        from context_service.db.queries import GET_WORKING_HYPOTHESES_FOR_SESSION
        from context_service.mcp.server import get_context_service

        ctx_svc = get_context_service()
        session_id = auth.session_id

        if session_id:
            rows = await ctx_svc.graph_store.execute_query(
                GET_WORKING_HYPOTHESES_FOR_SESSION,
                {"session_id": session_id, "silo_id": silo_id},
            )
            result["hypotheses"] = [
                {
                    "belief_id": r["belief_id"],
                    "content": r["content"],
                    "confidence": r["confidence"],
                    "about": r.get("about_ids", []),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        else:
            result["hypotheses"] = []

    return result


async def _track_node_access(
    silo_id: str, session_id: str, results: list[dict[str, Any]]
) -> None:
    """Track that nodes were accessed by this session for evidence accessibility."""
    from context_service.engine import queries
    from context_service.mcp.server import get_context_service

    import structlog

    log = structlog.get_logger(__name__)

    try:
        ctx = get_context_service()
        store = ctx._memgraph

        # Ensure session node exists (idempotent)
        await store.execute_write(
            queries.ENSURE_SESSION_NODE,
            {"session_id": session_id, "silo_id": silo_id},
        )

        # Mark each retrieved node as accessed
        for item in results:
            node_id = item.get("node_id")
            if not node_id:
                continue
            try:
                await store.execute_write(
                    queries.MARK_NODE_ACCESSED,
                    {"node_id": node_id, "silo_id": silo_id, "session_id": session_id},
                )
            except Exception as e:
                # Non-fatal: log and continue
                log.warning("mark_node_accessed_failed", node_id=node_id, error=str(e))
    except Exception as e:
        # Non-fatal: don't break recall on tracking failure
        log.warning("track_node_access_failed", error=str(e))


def register(mcp: FastMCP) -> None:
    """Register the recall tool."""

    @mcp.tool(
        name="recall",
        description=get_tool_description("recall"),
    )
    async def recall(
        query: str | None = None,
        node_ids: list[str] | None = None,
        depth: int = 0,
        layers: list[str] | None = None,
        top_k: int | None = None,
        include_hypotheses: bool = False,
    ) -> dict[str, Any]:
        """Retrieve knowledge.

        Args:
            query: Natural language search.
            node_ids: Specific nodes to fetch.
            depth: 0=flat, 1-3=graph traversal.
            layers: Filter: memory|knowledge|wisdom|intelligence.
            top_k: Max results for search (default 10, or preset value).
            include_hypotheses: Include tentative beliefs from current session.

        Returns:
            {results|nodes, hypotheses?, ...}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _recall_impl(query, node_ids, depth, layers, top_k, include_hypotheses)
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("recall", (time.perf_counter() - start) * 1000, success=success)
