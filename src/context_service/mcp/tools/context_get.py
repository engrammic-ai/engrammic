# context_service/mcp/tools/context_get.py
"""MCP tool: context_get - Retrieve context nodes by ID."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register the context_get tool on the MCP server."""

    @mcp.tool(
        name="context_get",
        description=(
            "Retrieve one or more context nodes by their IDs. "
            "Returns full node data including content, properties, and version. "
            "Pass as_of (ISO 8601) to retrieve the node state at a point in time."
        ),
    )
    async def context_get(
        node_ids: str | list[str],
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve context nodes by ID.

        Args:
            node_ids: A single node ID string or a list of node ID strings.
            as_of: Optional ISO 8601 timestamp for point-in-time retrieval.

        Returns:
            Dictionary with 'nodes' list containing node data.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        get_context_service()

        if isinstance(node_ids, str):
            node_ids = [node_ids]

        # TODO: Implement when ContextService is ported
        raise NotImplementedError(
            f"context_get not yet implemented. "
            f"org_id={auth.org_id}, node_ids={node_ids}, as_of={as_of}"
        )
