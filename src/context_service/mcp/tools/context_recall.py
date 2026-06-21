"""MCP tool: context_recall - Unified read tool for all EAG layers."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from context_service.mcp.server import get_mcp_auth_context
from context_service.mcp.tools.context_get import _context_get
from context_service.mcp.tools.context_graph import _context_graph
from context_service.mcp.tools.context_query import _context_query
from context_service.retrieval.coherence import filter_dominated_contradictions
from context_service.retrieval.fusion import FusionRetriever, _filter_temporal, _parse_relative_time
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.telemetry.metrics import record_context_recall_size, record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _fetch_chain_steps(
    chain_ids: list[str],
    postgres_store: Any | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch reasoning chain steps from Postgres for the given chain IDs.

    Returns a mapping of chain_id -> steps list. Chain IDs with no stored
    steps are omitted from the result.
    """
    if postgres_store is None:
        from context_service.mcp.server import get_postgres_store

        postgres_store = get_postgres_store()

    result: dict[str, list[dict[str, Any]]] = {}
    uuids = [UUID(cid) for cid in chain_ids]
    steps_map = await postgres_store.get_chain_steps_batch(uuids)
    for chain_id, steps in steps_map.items():
        if steps:
            result[str(chain_id)] = steps
    return result


_SUMMARY_MAX_CHARS = 200


def _project_node_without_content(
    node: dict[str, Any], include_expandable: bool = False
) -> dict[str, Any]:
    """Project a node dict to {node_id, layer, summary, created_at, confidence, tier}.

    `summary` falls back to the first 200 chars of `content` when no
    pre-computed summary is present. Error/sentinel entries are passed
    through unchanged so callers still see them.
    """
    if "node_id" not in node or "error" in node:
        return node

    summary = node.get("summary")
    if not summary:
        content = node.get("content") or ""
        summary = content[:_SUMMARY_MAX_CHARS] if content else None

    projected = {
        "node_id": node["node_id"],
        "layer": node.get("layer"),
        "summary": summary,
        "created_at": node.get("created_at"),
        "confidence": node.get("confidence"),
        "tier": node.get("tier", "COLD"),
        "relevance_score": node.get("relevance_score"),
    }
    if node.get("status") is not None:
        projected["status"] = node["status"]
    if node.get("type") == "ProposedBelief" and "status" not in projected:
        projected["status"] = "pending"
    if include_expandable:
        projected["expandable"] = True
    if "steps" in node:
        projected["steps"] = node["steps"]
    if "reflections" in node:
        projected["reflections"] = node["reflections"]
    return projected


def _strip_content(response: dict[str, Any]) -> dict[str, Any]:
    """Remove content from any node/result lists in a recall response."""
    if isinstance(response.get("nodes"), list):
        response["nodes"] = [_project_node_without_content(n) for n in response["nodes"]]
    if isinstance(response.get("results"), list):
        response["results"] = [_project_node_without_content(r) for r in response["results"]]
    return response


def _apply_tier_content_policy(
    response: dict[str, Any],
    include_content: bool | None,
) -> dict[str, Any]:
    """Apply tier-based content policy to response nodes.

    - include_content=True: return full content for all nodes
    - include_content=False: return summary for all nodes
    - include_content=None: HOT/WARM get content, COLD gets summary

    Returns a new dict to avoid mutating the input.
    """
    if include_content is True:
        return response
    if include_content is False:
        return _strip_content(response)

    # Tier-based logic for include_content=None - return copy to avoid mutation
    result = dict(response)

    def process_node(node: dict[str, Any]) -> dict[str, Any]:
        if "node_id" not in node or "error" in node:
            return node
        tier = node.get("tier", "COLD")
        if tier in ("HOT", "WARM"):
            return node
        return _project_node_without_content(node, include_expandable=True)

    if isinstance(response.get("nodes"), list):
        result["nodes"] = [process_node(n) for n in response["nodes"]]
    if isinstance(response.get("results"), list):
        result["results"] = [process_node(r) for r in response["results"]]
    return result


async def _fetch_pending_proposals(silo_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Fetch pending ProposedBelief nodes for a silo."""
    from context_service.db.queries import GET_PROPOSED_BELIEFS_FOR_SILO
    from context_service.mcp.server import get_context_service

    svc = get_context_service()
    rows = await svc.graph_store.execute_query(
        GET_PROPOSED_BELIEFS_FOR_SILO,
        {"silo_id": silo_id, "limit": limit},
    )
    return [
        {
            "node_id": r["proposed_belief_id"],
            "layer": "wisdom",
            "node_type": "ProposedBelief",
            "content": r["content"],
            "confidence": r["confidence"],
            "created_at": r["created_at"],
            "source_fact_ids": r["source_fact_ids"],
            "status": "pending",
        }
        for r in rows
    ]


def _filter_inactive_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove nodes whose properties.state is SUPERSEDED or TOMBSTONED.

    Nodes without a state set are treated as active (backward compat).
    Error sentinel entries (no node_id) are passed through unchanged.
    """
    active_states = {None, "ACTIVE"}
    return [
        n for n in nodes
        if "node_id" not in n or "error" in n
        or n.get("properties", {}).get("state") in active_states
    ]


async def _context_recall(
    silo_id: str,
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
    include_reflections: bool = False,
    reflections_agent_id: str | None = None,
    include_steps: bool = False,
    include_content: bool | None = None,
    include_proposals: bool = False,
    bypass_cache: bool = False,
    max_age_seconds: int | None = None,
    min_threshold: float | None = None,
    fusion_mode: bool = False,
    since: str | None = None,
    until: str | None = None,
    graph_depth: int | None = None,
    include_hints: bool = False,
    coherent: bool = False,
    include_inactive: bool = False,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if not query and not node_ids:
        return {"error": "missing_input", "message": "Provide query or node_ids"}

    if fusion_mode and not query:
        return {"error": "fusion_requires_query", "message": "fusion_mode=True requires a query"}

    # Fusion mode: run semantic + graph in parallel, fuse with RRF
    if fusion_mode and query:
        from context_service.config.settings import get_settings
        from context_service.mcp.server import get_context_service

        ctx_svc = get_context_service()
        settings = get_settings()
        fusion_cfg = settings.retrieval.fusion

        # Build scope context (need org_id from auth)
        auth = await get_mcp_auth_context()
        scope = ScopeContext(org_id=auth.org_id, silo_id=UUID(silo_id))

        # Create retriever with config
        retriever = FusionRetriever(ctx_svc, k=fusion_cfg.rrf_k)
        effective_graph_depth = (
            graph_depth
            if graph_depth is not None
            else (depth if depth > 0 else fusion_cfg.default_graph_depth)
        )

        # Run fusion
        # Pass top_k * 2 here to give temporal filtering headroom. FusionRetriever
        # fetches 4x from each channel internally but fuses down to this top_k * 2
        # before returning, so temporal filter sees 2x candidates.
        fused = await retriever.retrieve(
            query=query,
            scope=scope,
            top_k=top_k * 2,
            graph_depth=effective_graph_depth,
            layers=layers,
        )

        # Apply temporal filter if since/until provided
        now = datetime.now(UTC)
        try:
            since_dt = _parse_relative_time(since, now) if since else None
            until_dt = _parse_relative_time(until, now) if until else None
        except ValueError as e:
            return {"error": "invalid_time_format", "message": str(e)}

        if since_dt or until_dt:
            fused = await _filter_temporal(
                results=fused,
                since=since_dt,
                until=until_dt,
                store=ctx_svc.graph_store,
                silo_id=silo_id,
            )

        # Build fusion_meta once so both empty and non-empty paths use the same shape
        fusion_meta = {
            "enabled": True,
            "rrf_k": fusion_cfg.rrf_k,
            "graph_depth": effective_graph_depth,
            "temporal_filter": {"since": since, "until": until} if (since or until) else None,
        }

        # Take top_k after filtering
        fused = fused[:top_k]

        # Convert to standard response format
        if not fused:
            return {
                "results": [],
                "total_candidates": 0,
                "fusion_meta": fusion_meta,
            }

        # Fetch full node data for fused results
        node_ids_to_fetch = [r.node_id for r in fused]
        response = await _context_get(
            node_ids=node_ids_to_fetch,
            silo_id=silo_id,
            as_of=as_of,
            include_reflections=include_reflections,
            reflections_agent_id=reflections_agent_id,
        )

        # Add RRF scores to results
        rrf_scores = {r.node_id: r.rrf_score for r in fused}
        channel_contribs = {r.node_id: r.channel_contributions for r in fused}

        if isinstance(response.get("nodes"), list):
            for node in response["nodes"]:
                nid = node.get("node_id")
                if nid in rrf_scores:
                    node["rrf_score"] = rrf_scores[nid]
                    node["channel_contributions"] = channel_contribs.get(nid, {})

        # Fetch epistemic edges and apply coherence filtering
        filtered_contradictions = 0
        if isinstance(response.get("nodes"), list) and response["nodes"]:
            node_ids_for_edges = [n["node_id"] for n in response["nodes"] if "node_id" in n]
            edges_by_node = await ctx_svc.graph_store.get_epistemic_edges_for_nodes(
                node_ids_for_edges, silo_id
            )
            for node in response["nodes"]:
                nid = node.get("node_id")
                if nid:
                    edges = edges_by_node.get(nid, {})
                    node["supports"] = edges.get("supports", [])
                    node["derived_from"] = edges.get("derived_from", [])
                    node["contradicts"] = edges.get("contradicts", [])

            # Apply coherence filter
            if settings.coherence_filter_enabled:
                response["nodes"], filtered_contradictions = filter_dominated_contradictions(
                    response["nodes"]
                )

        response["fusion_meta"] = fusion_meta
        response["filtered_contradictions"] = filtered_contradictions

        response = _apply_tier_content_policy(response, include_content)
        if include_proposals:
            response["pending_proposals"] = await _fetch_pending_proposals(silo_id)

        return response

    if node_ids and depth == 0:
        response = await _context_get(
            node_ids=node_ids,
            silo_id=silo_id,
            as_of=as_of,
            include_reflections=include_reflections,
            reflections_agent_id=reflections_agent_id,
        )

        if not include_inactive and isinstance(response.get("nodes"), list):
            response["nodes"] = _filter_inactive_nodes(response["nodes"])

        if include_steps and isinstance(response.get("nodes"), list):
            intelligence_ids = [
                n["node_id"]
                for n in response["nodes"]
                if n.get("layer") == "intelligence" and "node_id" in n
            ]
            if intelligence_ids:
                steps_by_id = await _fetch_chain_steps(intelligence_ids)
                for node in response["nodes"]:
                    nid = node.get("node_id")
                    if nid in steps_by_id:
                        node["steps"] = steps_by_id[nid]

        response = _apply_tier_content_policy(response, include_content)
        if include_proposals:
            response["pending_proposals"] = await _fetch_pending_proposals(silo_id)
        return response

    if node_ids and depth > 0:
        response = await _context_graph(
            silo_id=silo_id,
            seed_nodes=node_ids,
            max_depth=depth,
            layers=layers,
        )

        # Apply coherence filtering if requested
        filtered_contradictions = 0
        if coherent and isinstance(response.get("nodes"), list) and response["nodes"]:
            from context_service.mcp.server import get_context_service

            ctx_svc = get_context_service()
            node_ids_for_edges = [n["node_id"] for n in response["nodes"] if "node_id" in n]
            edges_by_node = await ctx_svc.graph_store.get_epistemic_edges_for_nodes(
                node_ids_for_edges, silo_id
            )
            for node in response["nodes"]:
                nid = node.get("node_id")
                if nid:
                    edges = edges_by_node.get(nid, {})
                    node["contradicts"] = edges.get("contradicts", [])

            response["nodes"], filtered_contradictions = filter_dominated_contradictions(
                response["nodes"]
            )
            response["filtered_contradictions"] = filtered_contradictions

        response = _apply_tier_content_policy(response, include_content)
        if include_proposals:
            response["pending_proposals"] = await _fetch_pending_proposals(silo_id)
        return response

    if query and depth == 0:
        is_wildcard = query in ("*", "")
        response = await _context_query(
            silo_id=silo_id,
            query=query,
            layers=layers,
            top_k=top_k,
            as_of=as_of,
            bypass_cache=bypass_cache,
            max_age_seconds=max_age_seconds,
            min_threshold=min_threshold,
            bypass_threshold=is_wildcard,
            include_hints=include_hints,
            include_superseded=include_inactive,
        )
        response = _apply_tier_content_policy(response, include_content)
        if include_proposals:
            response["pending_proposals"] = await _fetch_pending_proposals(silo_id)
        return response

    response = await _context_graph(
        silo_id=silo_id,
        query=query,
        max_depth=depth,
        max_nodes=top_k,
        layers=layers,
    )
    response = _apply_tier_content_policy(response, include_content)

    if include_proposals:
        proposals = await _fetch_pending_proposals(silo_id)
        response["pending_proposals"] = proposals

    return response


def register(mcp: FastMCP) -> None:
    """Register the context_recall tool."""

    @mcp.tool(
        name="context_recall",
        description=(
            "Unified read tool. "
            "Flat fetch by node_ids (depth=0), graph traversal (depth>0), "
            "semantic search by query (depth=0), or graph expansion from query (depth>0). "
            "Provide query or node_ids — not required together."
        ),
    )
    async def context_recall(
        query: str | None = None,
        node_ids: list[str] | None = None,
        depth: int = 0,
        layers: list[str] | None = None,
        top_k: int = 10,
        as_of: str | None = None,
        silo_id: str | None = None,
        include_reflections: bool = False,
        reflections_agent_id: str | None = None,
        include_steps: bool = False,
        include_content: bool | None = None,
        include_proposals: bool = False,
        bypass_cache: bool = False,
        max_age_seconds: int | None = None,
        min_threshold: float | None = None,
        fusion_mode: bool = False,
        since: str | None = None,
        until: str | None = None,
        graph_depth: int | None = None,
        coherent: bool = False,
        include_inactive: bool = False,
    ) -> dict[str, Any]:
        """Unified read across Memory, Knowledge, Wisdom, and Intelligence layers.

        Args:
            query: Natural language search query. Mutually exclusive with node_ids
                at depth=0, combinable at depth>0.
            node_ids: Explicit node IDs to fetch or use as graph seeds.
            depth: 0 = flat lookup/search, 1-3 = graph traversal.
            layers: Filter results to specific layers: memory, knowledge, wisdom, intelligence.
            top_k: Maximum results for search mode (default 10).
            as_of: ISO 8601 datetime for time-travel (flat modes only).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            include_reflections: When True and fetching by node_ids at depth=0,
                attach MetaObservation reflections to each returned node.
            reflections_agent_id: Optional agent ID to filter reflections. When
                provided with include_reflections=True, only observations created
                by that agent are returned. Omit to return all agents' observations.
            include_steps: When True and fetching intelligence-layer nodes by
                node_ids at depth=0, attach reasoning chain steps stored in
                Postgres to each matching node. Silently ignored in search and
                traversal modes.
            include_content: When True (default), each node carries its full
                content and properties. When False, nodes are projected to
                {node_id, layer, summary, created_at, confidence}, where summary
                falls back to the first 200 characters of content if no
                pre-computed summary exists. Useful for cheap browsing or
                pagination before a follow-up fetch by node_id.
            include_proposals: When True, append pending ProposedBelief nodes
                to the response in a `pending_proposals` field.
            bypass_cache: When True, skip the result cache and force a fresh
                search. Only applies to query + depth=0 mode.
            max_age_seconds: Maximum acceptable cache age in seconds. If the
                cached result is older than this, a fresh search is performed.
                Only applies to query + depth=0 mode.
            min_threshold: Minimum relevance score threshold for results.
                Only applies to query + depth=0 mode.
            fusion_mode: When True, runs semantic and graph retrieval in parallel
                and fuses results with Reciprocal Rank Fusion. Requires query.
            since: Filter results to nodes created at or after this time. Accepts
                relative strings ("7d", "1w", "30d") or ISO datetime.
            until: Filter results to nodes created at or before this time. Same
                format as since.
            graph_depth: BFS depth for graph channel in fusion_mode. Defaults to
                config value (2). Overrides depth when fusion_mode=True.
            coherent: When True and using graph traversal (node_ids + depth > 0),
                filter out dominated contradictions to return a coherent view.
                Default False preserves full graph structure including contradictions.
            include_inactive: When False (default), superseded and tombstoned nodes
                are excluded from all results. When True, all nodes regardless of
                their lifecycle state are returned. Useful for auditing supersession
                chains or debugging stale content.

        Returns:
            Depends on mode:
            - node_ids + depth=0: {nodes}
            - node_ids + depth>0: {nodes, edges, traversal_stats, metadata}
            - query + depth=0: {results, total_candidates, search_time_ms}
            - query + depth>0: {nodes, edges, traversal_stats, metadata}
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        start = time.perf_counter()
        success = True
        try:
            result = await _context_recall(
                silo_id=resolved_silo_id,
                query=query,
                node_ids=node_ids,
                depth=depth,
                layers=layers,
                top_k=top_k,
                as_of=as_of,
                include_reflections=include_reflections,
                reflections_agent_id=reflections_agent_id,
                include_steps=include_steps,
                include_content=include_content,
                include_proposals=include_proposals,
                bypass_cache=bypass_cache,
                max_age_seconds=max_age_seconds,
                min_threshold=min_threshold,
                fusion_mode=fusion_mode,
                since=since,
                until=until,
                graph_depth=graph_depth,
                coherent=coherent,
                include_inactive=include_inactive,
            )
            node_count = len(result.get("results", result.get("nodes", [])))
            avg_node_bytes = 500 if include_content else 100
            estimated_bytes = node_count * avg_node_bytes + 200
            layer_name = (
                (layers[0] if layers and len(layers) == 1 else "mixed") if layers else "all"
            )
            record_context_recall_size(layer_name, estimated_bytes)
            return result
        except Exception:
            success = False
            raise
        finally:
            # Note: Sub-tools (_context_get, _context_query, _context_graph) also emit
            # their own metrics with their respective names when dispatched from here.
            record_mcp_tool("context_recall", (time.perf_counter() - start) * 1000, success=success)
