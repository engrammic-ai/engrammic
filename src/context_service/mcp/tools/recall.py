# src/context_service/mcp/tools/recall.py
"""MCP tool: recall - Search or fetch knowledge."""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

from context_service.engine.engagement import MODE_HARD
from context_service.mcp.error_boundary import mcp_error_boundary
from context_service.mcp.rate_limit import rate_limited
from context_service.mcp.server import (
    get_mcp_auth_context,
    get_preset_resolver,
    get_redis,
    track_tool_usage,
)
from context_service.mcp.tools.context_recall import _context_recall
from context_service.mcp.tools.registry import get_tool_description
from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import (
    record_engagement_latency,
    record_mcp_tool,
    record_recall_depth,
    record_recall_latency,
    record_recall_result_count,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP


@rate_limited("recall")
async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "recall")
    silo_id = str(derive_silo_id(auth.org_id))

    effective_top_k = top_k
    if effective_top_k is None:
        effective_top_k = 10
        try:
            preset = await get_preset_resolver().resolve(silo_id)
            override = preset.param_overrides.get("default_recall_top_k")
            if isinstance(override, int) and not isinstance(override, bool) and override > 0:
                effective_top_k = override
        except RuntimeError:
            pass

    start = time.perf_counter()
    result = await _context_recall(
        silo_id=silo_id,
        query=query,
        node_ids=node_ids,
        depth=depth,
        layers=layers,
        top_k=effective_top_k,
        bypass_cache=bypass_cache,
        max_age_seconds=max_age_seconds,
    )
    duration_ms = (time.perf_counter() - start) * 1000

    # Determine source path taken for latency attribution
    cache_meta = result.get("cache_meta")
    if cache_meta is not None:
        source = "cache" if cache_meta.get("result_cached") else "search"
    elif "edges" in result:
        source = "graph"
    else:
        source = "get"

    with contextlib.suppress(Exception):
        record_recall_latency(duration_ms, depth=depth, source=source, silo_id=silo_id)
        record_recall_depth(depth, silo_id=silo_id)
        result_list = result.get("results") or result.get("nodes") or []
        layer_label = (layers[0] if layers and len(layers) == 1 else "mixed") if layers else "all"
        record_recall_result_count(len(result_list), layer=layer_label, silo_id=silo_id)

    result_list = result.get("results") or result.get("nodes") or []

    # Track node access for evidence accessibility (Layer 3 chain reuse)
    # Fire-and-forget to avoid blocking recall hot path
    session_id = auth.session_id
    if session_id and result.get("results"):
        import asyncio

        asyncio.create_task(_track_node_access(silo_id, session_id, result["results"]))

    # Engagement detection: check for markers touching the about-set
    about_ids = [item.get("node_id") for item in result_list if item.get("node_id")]
    redis = get_redis()
    effective_session_id = session_id or "default"
    if about_ids and redis is not None:
        engagement_start = time.perf_counter()
        try:
            from context_service.engine.engagement import get_engagement_for_about_set
            from context_service.mcp.server import get_context_service

            ctx = get_context_service()
            engagement = await get_engagement_for_about_set(
                redis._redis, ctx._memgraph, silo_id, about_ids,
                session_id=effective_session_id,
            )
            result["engagement"] = engagement
            engagement_ms = (time.perf_counter() - engagement_start) * 1000
            with contextlib.suppress(Exception):
                record_engagement_latency(engagement_ms, silo_id=silo_id)
        except Exception:
            # Non-fatal: don't break recall on engagement detection failure
            import structlog

            structlog.get_logger(__name__).warning(
                "engagement_detection_failed", silo_id=silo_id
            )
            result["engagement"] = None
    else:
        result["engagement"] = None

    # Hard checkpoint enforcement: when engagement mode is "hard", suppress
    # all results so the agent has no content to act on until markers are resolved.
    hard_mode = bool(
        result.get("engagement") and result["engagement"].get("mode") == MODE_HARD
    )
    if hard_mode:
        result["results"] = []
        if "nodes" in result:
            result["nodes"] = []
        if include_hypotheses:
            result["hypotheses"] = []

    if include_hypotheses and not hard_mode:
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


async def _track_node_access(silo_id: str, session_id: str, results: list[dict[str, Any]]) -> None:
    """Track that nodes were accessed by this session for evidence accessibility."""
    import structlog

    from context_service.engine import queries
    from context_service.mcp.server import get_context_service

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
    @mcp_error_boundary
    async def recall(
        query: str | None = None,
        node_ids: list[str] | None = None,
        depth: int = 0,
        layers: list[str] | None = None,
        top_k: int | None = None,
        include_hypotheses: bool = False,
        bypass_cache: bool = False,
        max_age_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve knowledge.

        Args:
            query: Natural language search.
            node_ids: Specific nodes to fetch.
            depth: 0=flat, 1-3=graph traversal.
            layers: Filter: memory|knowledge|wisdom|intelligence.
            top_k: Max results for search (default 10, or preset value).
            include_hypotheses: Include tentative beliefs from current session.
            bypass_cache: When True, skip the result cache and force a fresh
                search. Only applies to query + depth=0 mode.
            max_age_seconds: Maximum acceptable cache age in seconds. If the
                cached result is older than this, a fresh search is performed.
                Only applies to query + depth=0 mode.

        Returns:
            {results|nodes, hypotheses?, ...}
        """
        start = time.perf_counter()
        success = True
        try:
            return await _recall_impl(
                query,
                node_ids,
                depth,
                layers,
                top_k,
                include_hypotheses,
                bypass_cache,
                max_age_seconds,
            )
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("recall", (time.perf_counter() - start) * 1000, success=success)
