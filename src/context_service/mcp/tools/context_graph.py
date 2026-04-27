"""MCP tool: context_graph - Graph traversal from semantic seed."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.mcp.auth import get_mcp_auth
from context_service.mcp.server import get_context_service
from context_service.models.mcp import Layer
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_graph(
    silo_id: str,
    query: str | None = None,
    seed_nodes: list[str] | None = None,
    max_depth: int = 2,
    max_nodes: int = 50,
    relationship_types: list[str] | None = None,
    layers: list[str] | None = None,
) -> dict[str, Any]:
    auth = get_mcp_auth()
    ctx_svc = get_context_service()

    expected_silo_id = derive_silo_id(auth.org_id)
    try:
        requested = uuid.UUID(silo_id)
    except ValueError:
        return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

    if requested != expected_silo_id:
        return {"error": "silo_not_found", "silo_id": silo_id}

    if not query and not seed_nodes:
        return {"error": "missing_seed", "message": "Provide query or seed_nodes"}

    if max_depth < 1 or max_depth > 5:
        return {"error": "invalid_max_depth", "message": "max_depth must be between 1 and 5"}

    if max_nodes < 1 or max_nodes > 200:
        return {"error": "invalid_max_nodes", "message": "max_nodes must be between 1 and 200"}

    if layers:
        try:
            [Layer(layer) for layer in layers]
        except ValueError:
            return {"error": "invalid_layer", "valid": [e.value for e in Layer]}

    result = await ctx_svc.graph_traversal(
        silo_id=str(expected_silo_id),
        query=query,
        seed_nodes=seed_nodes,
        max_depth=max_depth,
        max_nodes=max_nodes,
        relationship_types=relationship_types,
        layers=layers,
    )

    return {
        "nodes": result.nodes,
        "edges": result.edges,
        "traversal_stats": {
            "depth_reached": result.depth_reached,
            "nodes_visited": result.nodes_visited,
            "edges_traversed": result.edges_traversed,
        },
    }


def register(mcp: FastMCP) -> None:
    """Register the context_graph tool."""

    @mcp.tool(
        name="context_graph",
        description=(
            "Graph traversal from a semantic query or specific seed nodes. "
            "Returns subgraph with nodes, edges, and traversal stats. "
            "Target: < 500ms for depth 2."
        ),
    )
    async def context_graph(
        silo_id: str,
        query: str | None = None,
        seed_nodes: list[str] | None = None,
        max_depth: int = 2,
        max_nodes: int = 50,
        relationship_types: list[str] | None = None,
        layers: list[str] | None = None,
    ) -> dict[str, Any]:
        """Graph traversal from semantic seed.

        Args:
            silo_id: UUID of the silo.
            query: Semantic query to find seed nodes (requires embedding service).
            seed_nodes: Explicit starting node IDs (list of node ID strings).
            max_depth: Traversal depth 1-5 (default 2).
            max_nodes: Maximum nodes to return 1-200 (default 50).
            relationship_types: Filter edges by type (e.g. REFERENCES, SUPPORTS).
            layers: Filter nodes to specific layers (memory, knowledge, wisdom).

        Returns:
            {nodes, edges, traversal_stats}
        """
        return await _context_graph(
            silo_id=silo_id,
            query=query,
            seed_nodes=seed_nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
            relationship_types=relationship_types,
            layers=layers,
        )
