"""MCP tool: context_graph - Graph traversal from semantic seed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.config.settings import get_settings
from context_service.mcp.server import get_context_service, get_mcp_auth_context, get_silo_service
from context_service.models.mcp import Layer
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import validate_silo_ownership

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
    auth = await get_mcp_auth_context()
    ctx_svc = get_context_service()

    silo_service = get_silo_service()
    err = await validate_silo_ownership(silo_service, silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

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

    settings = get_settings()
    effective_rel_types = list(relationship_types) if relationship_types else None
    if settings.causal.query_enabled:
        causal_types = ["CAUSES", "CORROBORATES", "PREVENTS"]
        if effective_rel_types is None:
            effective_rel_types = causal_types
        else:
            for ct in causal_types:
                if ct not in effective_rel_types:
                    effective_rel_types.append(ct)
    if settings.session_compaction_enabled:
        if effective_rel_types is None:
            effective_rel_types = ["REFERENCES"]
        elif "REFERENCES" not in effective_rel_types:
            effective_rel_types.append("REFERENCES")

    result = await ctx_svc.graph_traversal(
        silo_id=str(expected_silo_id),
        query=query,
        seed_nodes=seed_nodes,
        max_depth=max_depth,
        max_nodes=max_nodes,
        relationship_types=effective_rel_types,
        layers=layers,
    )

    metadata: dict[str, Any] = {
        "causal_edges_enabled": settings.causal.query_enabled,
        "references_edges_enabled": settings.session_compaction_enabled,
    }

    if settings.causal.query_enabled:
        scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
        silo = await silo_service.get_by_id(scope)
        if silo is not None:
            coverage_from = silo.metadata.get("causal_coverage_from")
            if coverage_from is not None:
                metadata["causal_coverage_from"] = coverage_from

    return {
        "nodes": result.nodes,
        "edges": result.edges,
        "traversal_stats": {
            "depth_reached": result.depth_reached,
            "nodes_visited": result.nodes_visited,
            "edges_traversed": result.edges_traversed,
        },
        "metadata": metadata,
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
        query: str | None = None,
        seed_nodes: list[str] | None = None,
        max_depth: int = 2,
        max_nodes: int = 50,
        relationship_types: list[str] | None = None,
        layers: list[str] | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Graph traversal from semantic seed.

        Args:
            query: Semantic query to find seed nodes (requires embedding service).
            seed_nodes: Explicit starting node IDs (list of node ID strings).
            max_depth: Traversal depth 1-5 (default 2).
            max_nodes: Maximum nodes to return 1-200 (default 50).
            relationship_types: Filter edges by type (e.g. REFERENCES, SUPPORTS).
            layers: Filter nodes to specific layers (memory, knowledge, wisdom).
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {nodes, edges, traversal_stats, metadata}
            edges include an ``inferred`` bool on causal edges.
            metadata includes ``causal_edges_enabled`` and, when set on the silo,
            ``causal_coverage_from`` (epoch from which causal coverage applies).
        """
        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_graph(
            silo_id=resolved_silo_id,
            query=query,
            seed_nodes=seed_nodes,
            max_depth=max_depth,
            max_nodes=max_nodes,
            relationship_types=relationship_types,
            layers=layers,
        )
