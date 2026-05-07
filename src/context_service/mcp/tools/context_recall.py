"""MCP tool: context_recall - Unified read tool for all EAG layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from context_service.mcp.server import get_mcp_auth_context
from context_service.mcp.tools.context_get import _context_get
from context_service.mcp.tools.context_graph import _context_graph
from context_service.mcp.tools.context_query import _context_query
from context_service.mcp.tools.errors import error_response
from context_service.services.models import derive_silo_id

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
        from context_service.engine.postgres_store import PostgresStore

        postgres_store = PostgresStore()

    result: dict[str, list[dict[str, Any]]] = {}
    uuids = [UUID(cid) for cid in chain_ids]
    steps_map = await postgres_store.get_chain_steps_batch(uuids)
    for chain_id, steps in steps_map.items():
        if steps:
            result[str(chain_id)] = steps
    return result


_SUMMARY_MAX_CHARS = 200


def _project_node_without_content(node: dict[str, Any]) -> dict[str, Any]:
    """Project a node dict to {node_id, layer, summary, created_at, confidence}.

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

    return {
        "node_id": node["node_id"],
        "layer": node.get("layer"),
        "summary": summary,
        "created_at": node.get("created_at"),
        "confidence": node.get("confidence"),
    }


def _strip_content(response: dict[str, Any]) -> dict[str, Any]:
    """Remove content from any node/result lists in a recall response."""
    if isinstance(response.get("nodes"), list):
        response["nodes"] = [_project_node_without_content(n) for n in response["nodes"]]
    if isinstance(response.get("results"), list):
        response["results"] = [_project_node_without_content(r) for r in response["results"]]
    return response


_PROPOSED_BELIEFS_LIMIT = 5


async def _fetch_proposed_beliefs(silo_id: str) -> list[dict[str, Any]]:
    """Fetch pending ProposedBeliefs for the given silo.

    Returns a list of proposal dicts, or an empty list if none are found or
    the query fails.
    """
    from context_service.db import queries as q
    from context_service.mcp.server import get_context_service

    store = get_context_service().graph_store
    rows = await store.execute_query(
        q.GET_PROPOSED_BELIEFS,
        {"silo_id": silo_id, "status": "pending", "limit": _PROPOSED_BELIEFS_LIMIT},
    )

    proposals: list[dict[str, Any]] = []
    for row in rows:
        pb = row.get("pb")
        if pb is None:
            continue
        proposals.append(
            {
                "id": pb.get("id"),
                "content": pb.get("content"),
                "confidence": pb.get("confidence"),
                "evidence_ids": pb.get("evidence_ids") or [],
                "created_at": pb.get("created_at"),
            }
        )
    return proposals


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
    include_content: bool = True,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if not query and not node_ids:
        return error_response(
            "VALIDATION_ERROR",
            "Provide query or node_ids",
            details={"fields": ["query", "node_ids"]},
        )

    ignored: list[str] = []

    if node_ids and depth == 0:
        response = await _context_get(
            node_ids=node_ids,
            silo_id=silo_id,
            as_of=as_of,
            include_reflections=include_reflections,
            reflections_agent_id=reflections_agent_id,
        )

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

        if not include_content:
            response = _strip_content(response)
    elif node_ids and depth > 0:
        if include_steps:
            ignored.append("include_steps")
        if include_reflections:
            ignored.append("include_reflections")
        response = await _context_graph(
            silo_id=silo_id,
            seed_nodes=node_ids,
            max_depth=depth,
            layers=layers,
        )
        if not include_content:
            response = _strip_content(response)
    elif query and depth == 0:
        if include_steps:
            ignored.append("include_steps")
        if include_reflections:
            ignored.append("include_reflections")
        response = await _context_query(
            silo_id=silo_id,
            query=query,
            layers=layers,
            top_k=top_k,
            as_of=as_of,
        )
        if not include_content:
            response = _strip_content(response)
    else:
        if include_steps:
            ignored.append("include_steps")
        if include_reflections:
            ignored.append("include_reflections")
        response = await _context_graph(
            silo_id=silo_id,
            query=query,
            max_depth=depth,
            max_nodes=top_k,
            layers=layers,
        )
        if not include_content:
            response = _strip_content(response)

    proposed = await _fetch_proposed_beliefs(silo_id)
    if proposed:
        response["proposed_beliefs"] = proposed

    if ignored:
        response["ignored_flags"] = ignored

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
        include_content: bool = True,
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

        Returns:
            Depends on mode:
            - node_ids + depth=0: {nodes}
            - node_ids + depth>0: {nodes, edges, traversal_stats, metadata}
            - query + depth=0: {results, total_candidates, search_time_ms}
            - query + depth>0: {nodes, edges, traversal_stats, metadata}
            All modes append {proposed_beliefs} when pending proposals exist for
            the silo. Each entry has {id, content, confidence, evidence_ids,
            created_at}. Use context_accept_belief or context_reject_belief to
            act on proposals.
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_recall(
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
        )
