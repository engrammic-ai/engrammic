# context_service/mcp/tools/context_lookup.py
"""MCP tool: context_lookup - Semantic search for context nodes."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register the context_lookup tool on the MCP server."""

    @mcp.tool(
        name="context_lookup",
        description=(
            "Search for context nodes by semantic similarity with graph expansion. "
            "Returns ranked results with similarity scores and graph distance. "
            "Pass as_of (ISO 8601) to scope results to that point in time."
        ),
    )
    async def context_lookup(
        query: str,
        silo_ids: list[str] | None = None,
        depth: int = 2,
        max_nodes: int = 50,
        max_tokens: int | None = None,  # noqa: ARG001
        type_filter: str | None = None,
        as_of: str | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        """Perform semantic search with graph-walk expansion.

        Args:
            query: Natural language search query.
            silo_ids: Optional list of silo UUIDs to search within.
            depth: Graph traversal depth (default 2, max 5).
            max_nodes: Maximum results (default 50).
            max_tokens: Optional token budget for results (not yet implemented).
            type_filter: Optional filter by node type.
            as_of: Optional ISO 8601 timestamp for point-in-time scoping (not yet implemented).

        Returns:
            Dictionary with nodes, silos_searched, total_candidates.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        resolved_uuids: list[uuid.UUID] | None = None
        if silo_ids is not None:
            org_silo = derive_silo_id(auth.org_id)
            resolved_uuids = []
            for sid in silo_ids:
                try:
                    parsed = uuid.UUID(sid)
                except ValueError:
                    return {"error": "invalid_silo_id", "silo_id": sid, "message": "silo_id must be a valid UUID"}
                if parsed != org_silo:
                    return {
                        "error": "silo_not_found",
                        "silo_id": sid,
                        "message": "Silo does not exist or org_id mismatch.",
                    }
                resolved_uuids.append(parsed)

        result = await ctx_svc.lookup(
            query=query,
            org_id=auth.org_id,
            silo_ids=resolved_uuids,
            max_nodes=max_nodes,
            type_filter=type_filter,
        )

        return {
            "nodes": [
                {
                    "node_id": str(n.node_id),
                    "content": n.content,
                    "type": n.type,
                    "silo_id": str(n.silo_id),
                    "score": n.score,
                    "properties": n.properties,
                }
                for n in result.nodes
            ],
            "silos_searched": [str(s) for s in result.silos_searched],
            "total_candidates": result.total_candidates,
            "depth": depth,
        }
