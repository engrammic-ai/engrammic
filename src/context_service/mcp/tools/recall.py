# src/context_service/mcp/tools/recall.py
"""MCP tool: recall - Search or fetch knowledge."""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING, Any

from context_service.config.settings import get_settings
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
from context_service.mcp.tools.trust_gate import apply_trust_gate
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
    min_threshold: float | None = None,
    include_withheld: bool = False,
    include_content: bool | None = True,
    fusion_mode: bool = False,
    since: str | None = None,
    until: str | None = None,
    graph_depth: int | None = None,
    include_hints: bool = False,
    include_inactive: bool = False,
    agent_id: str | None = None,
    exclude_agents: list[str] | None = None,
    include_conflicts: bool = False,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    await track_tool_usage(auth, "recall")
    silo_id = str(derive_silo_id(auth.org_id))

    MAX_DEPTH = 3
    depth = max(0, min(depth, MAX_DEPTH))

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

    MAX_TOP_K = 100
    effective_top_k = min(effective_top_k, MAX_TOP_K)

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
        min_threshold=min_threshold,
        include_content=include_content,
        fusion_mode=fusion_mode,
        since=since,
        until=until,
        graph_depth=graph_depth,
        include_hints=include_hints,
        include_inactive=include_inactive,
        agent_id=agent_id,
        exclude_agents=exclude_agents,
        include_conflicts=include_conflicts,
        tags=tags,
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

    # Surface conflict status and credibility on each result item.
    # Query-path items carry these as top-level fields (set by context_query.py).
    # Get-path items carry them inside `properties`; promote to top-level for
    # consistency so callers always see conflict_status / credibility / credibility_factors.
    has_unresolved_conflicts = False
    for item in result_list:
        if "error" in item:
            continue
        props = item.get("properties") or {}
        if "conflict_status" not in item:
            item["conflict_status"] = str(props.get("conflict_status") or "none")
        if "credibility" not in item:
            item["credibility"] = float(props.get("credibility") or 0.0)
        if "credibility_factors" not in item:
            raw_cf = props.get("credibility_factors")
            item["credibility_factors"] = raw_cf if isinstance(raw_cf, dict) else None
        if item.get("conflict_status") == "unresolved":
            has_unresolved_conflicts = True
    result["has_unresolved_conflicts"] = has_unresolved_conflicts

    # Track node access for evidence accessibility (Layer 3 chain reuse)
    # Fire-and-forget to avoid blocking recall hot path
    session_id = auth.session_id
    if session_id and result.get("results"):
        import asyncio

        asyncio.create_task(_track_node_access(silo_id, session_id, result["results"]))

    # Stuck detection: record query and check for stuck pattern
    if query and session_id:
        import asyncio

        asyncio.create_task(_check_stuck_pattern(silo_id, session_id, query))

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
                redis._redis,
                ctx._memgraph,
                silo_id,
                about_ids,
                session_id=effective_session_id,
            )
            result["engagement"] = engagement
            engagement_ms = (time.perf_counter() - engagement_start) * 1000
            with contextlib.suppress(Exception):
                record_engagement_latency(engagement_ms, silo_id=silo_id)
        except Exception:
            # Non-fatal: don't break recall on engagement detection failure
            import structlog

            structlog.get_logger(__name__).warning("engagement_detection_failed", silo_id=silo_id)
            result["engagement"] = None
    else:
        result["engagement"] = None

    # Hard checkpoint enforcement: when engagement mode is "hard", suppress
    # all results so the agent has no content to act on until markers are resolved.
    hard_mode = bool(result.get("engagement") and result["engagement"].get("mode") == MODE_HARD)
    if hard_mode:
        result["results"] = []
        result["message"] = "Results suppressed: engagement checkpoint requires resolution"
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

    tg = get_settings().trust_gate
    if tg.enabled:
        list_key = "results" if "results" in result else ("nodes" if "nodes" in result else None)
        if list_key is not None and isinstance(result[list_key], list):
            surfaced, withheld = apply_trust_gate(
                result[list_key],
                confidence_floor=tg.confidence_floor,
                withhold_conflicts=tg.withhold_unresolved_conflicts,
                include_withheld=include_withheld,
            )
            result[list_key] = surfaced
            if withheld["count"] > 0:
                withheld["message"] = (
                    f"{withheld['count']} memories withheld (low confidence or "
                    "unresolved contradiction). Pass include_withheld=true to see them."
                )
            result["withheld"] = withheld

    # Epistemic hints: surface past breakthroughs when agent might be stuck
    settings = get_settings()
    if settings.recall_hints_enabled and query and session_id:
        try:
            from context_service.engine.intelligence import (
                find_breakthrough_hints,
                get_active_stuck_indicator,
            )
            from context_service.mcp.server import get_context_service

            ctx = get_context_service()

            # Check if agent is stuck
            stuck = await get_active_stuck_indicator(ctx._memgraph, silo_id, session_id)
            if stuck:
                # Find similar past breakthroughs
                hints = await find_breakthrough_hints(ctx._memgraph, silo_id, query)
                if hints:
                    result["epistemic_hints"] = {
                        "stuck_on": stuck.get("query_pattern"),
                        "breakthroughs": hints,
                        "message": "You may be stuck. Here are past resolutions for similar queries.",
                    }
                else:
                    result["epistemic_hints"] = None
            else:
                result["epistemic_hints"] = None
        except Exception:
            import structlog

            structlog.get_logger(__name__).debug("epistemic_hints_failed", silo_id=silo_id)
            result["epistemic_hints"] = None
    else:
        result["epistemic_hints"] = None

    # Gap detection: record unanswered queries
    result_count = len(result.get("results") or result.get("nodes") or [])
    if query and result_count == 0:
        import asyncio

        asyncio.create_task(_record_knowledge_gap(silo_id, query))

    return result


async def _record_knowledge_gap(silo_id: str, query: str) -> None:
    """Record an unanswered query as a knowledge gap."""
    import structlog

    from context_service.engine.intelligence import record_knowledge_gap
    from context_service.mcp.server import get_context_service

    log = structlog.get_logger(__name__)

    try:
        ctx = get_context_service()
        await record_knowledge_gap(ctx._memgraph, silo_id, query)
    except Exception as e:
        log.debug("gap_recording_failed", error=str(e))


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


async def _check_stuck_pattern(silo_id: str, session_id: str, query: str) -> None:
    """Check for stuck pattern and create indicator if detected."""
    import structlog

    from context_service.engine.intelligence import (
        create_stuck_indicator,
        detect_stuck_pattern,
        get_active_stuck_indicator,
    )
    from context_service.engine.session_state import get_or_create_session, save_session
    from context_service.mcp.server import get_context_service, get_redis

    log = structlog.get_logger(__name__)

    try:
        redis = get_redis()
        if redis is None:
            return

        session = await get_or_create_session(redis._redis, session_id, silo_id)
        session.record_query(query)
        await save_session(redis._redis, session, silo_id)

        # Check for stuck pattern
        similar_queries = detect_stuck_pattern(session)
        if similar_queries:
            # Check if we already have an active indicator
            ctx = get_context_service()
            existing = await get_active_stuck_indicator(ctx._memgraph, silo_id, session_id)
            if not existing:
                await create_stuck_indicator(
                    ctx._memgraph,
                    silo_id,
                    session_id,
                    similar_queries,
                )
    except Exception as e:
        log.debug("stuck_detection_failed", error=str(e))


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
        min_threshold: float | None = None,
        include_withheld: bool = False,
        include_content: bool | None = True,
        fusion_mode: bool = False,
        since: str | None = None,
        until: str | None = None,
        graph_depth: int | None = None,
        include_hints: bool = False,
        include_inactive: bool = False,
        agent_id: str | None = None,
        exclude_agents: list[str] | None = None,
        include_conflicts: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Retrieve knowledge.

        Args:
            query: Natural language search.
            node_ids: Specific nodes to fetch.
            depth: 0=flat, 1-3=graph traversal.
            layers: Filter: memory|knowledge|wisdom|intelligence.
            top_k: Max results for search (default 10, or preset value).
            include_hypotheses: Deprecated (CITE v2). WorkingHypothesis node type removed.
                Always returns an empty list. Ignored.
            bypass_cache: When True, skip the result cache and force a fresh
                search. Only applies to query + depth=0 mode.
            max_age_seconds: Maximum acceptable cache age in seconds. If the
                cached result is older than this, a fresh search is performed.
                Only applies to query + depth=0 mode.
            min_threshold: Override relevance threshold (0.0-1.0). Lower values
                return more results. When query="*", threshold is bypassed.
            include_content: When True (default), return full node content.
                False returns summaries only. None defers to the tier policy
                (HOT/WARM return content, COLD returns a summary).
            fusion_mode: When True, runs semantic and graph retrieval in parallel
                and fuses with RRF. Requires query.
            since: Filter to nodes created at/after this time. Requires fusion_mode.
                Accepts relative ("7d", "1w", "30d") or ISO datetime.
            until: Filter to nodes created at/before this time. Same format as since.
            graph_depth: BFS depth for graph channel when fusion_mode=True.
                Defaults to config value (2). Overrides depth when fusion_mode=True.
            include_hints: When True, receive belief candidate suggestions when
                corroborating facts are detected.
            include_inactive: When False (default), superseded and tombstoned nodes
                are excluded from results. When True, all lifecycle states are
                returned. Useful for auditing supersession chains.
            agent_id: When provided, only return nodes created by this agent.
            exclude_agents: List of agent IDs whose nodes should be excluded
                from results.
            include_conflicts: When True, also return nodes that have CONTRADICTS
                edges to the result nodes, in a separate conflict_nodes field.
            tags: Filter to nodes having ALL specified tags.

        Returns:
            {results|nodes, hypotheses?, conflict_nodes?, ...}
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
                min_threshold,
                include_withheld=include_withheld,
                include_content=include_content,
                fusion_mode=fusion_mode,
                since=since,
                until=until,
                graph_depth=graph_depth,
                include_hints=include_hints,
                include_inactive=include_inactive,
                agent_id=agent_id,
                exclude_agents=exclude_agents,
                include_conflicts=include_conflicts,
                tags=tags,
            )
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool("recall", (time.perf_counter() - start) * 1000, success=success)
