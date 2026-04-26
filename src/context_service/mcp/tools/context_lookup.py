# context_service/mcp/tools/context_lookup.py
"""MCP tool: context_lookup - Semantic search for context nodes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
        max_tokens: int | None = None,
        type_filter: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Perform semantic search with graph-walk expansion.

        Args:
            query: Natural language search query.
            silo_ids: Optional list of silo UUIDs to search within.
            depth: Graph traversal depth (default 2, max 5).
            max_nodes: Maximum results (default 50).
            max_tokens: Optional token budget for results.
            type_filter: Optional filter by node type.
            as_of: Optional ISO 8601 timestamp for point-in-time scoping.

        Returns:
            Dictionary with nodes, silos_searched, total_candidates, token_estimate.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        service = get_context_service()

        # TODO: Implement when ContextService is ported
        raise NotImplementedError(
            f"context_lookup not yet implemented. "
            f"org_id={auth.org_id}, query={query[:50]}..., "
            f"silo_ids={silo_ids}, depth={depth}"
        )
