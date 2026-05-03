"""MCP tool: context_recall - Unified read tool for all EAG layers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.mcp.tools.context_get import _context_get
from context_service.mcp.tools.context_graph import _context_graph
from context_service.mcp.tools.context_query import _context_query
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_recall(
    silo_id: str,
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if not query and not node_ids:
        return {"error": "missing_input", "message": "Provide query or node_ids"}

    if node_ids and depth == 0:
        return await _context_get(node_ids=node_ids, silo_id=silo_id, as_of=as_of)

    if node_ids and depth > 0:
        return await _context_graph(
            silo_id=silo_id,
            seed_nodes=node_ids,
            max_depth=depth,
            layers=layers,
        )

    if query and depth == 0:
        return await _context_query(
            silo_id=silo_id,
            query=query,
            layers=layers,
            top_k=top_k,
            as_of=as_of,
        )

    return await _context_graph(
        silo_id=silo_id,
        query=query,
        max_depth=depth,
        max_nodes=top_k,
        layers=layers,
    )


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

        Returns:
            Depends on mode:
            - node_ids + depth=0: {nodes}
            - node_ids + depth>0: {nodes, edges, traversal_stats, metadata}
            - query + depth=0: {results, total_candidates, search_time_ms}
            - query + depth>0: {nodes, edges, traversal_stats, metadata}
        """
        from context_service.mcp.server import get_mcp_auth_context

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
        )
