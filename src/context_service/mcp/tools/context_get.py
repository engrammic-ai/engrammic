# context_service/mcp/tools/context_get.py
"""MCP tool: context_get - Retrieve context nodes by ID."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id
from context_service.services.silo import validate_silo_ownership

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
        silo_id: str | None = None,
        as_of: str | None = None,  # noqa: ARG001
    ) -> dict[str, Any]:
        """Retrieve context nodes by ID.

        Args:
            node_ids: A single node ID string or a list of node ID strings.
            silo_id: UUID of the silo to scope the lookup. Defaults to the org's primary silo.
            as_of: Optional ISO 8601 timestamp for point-in-time retrieval (not yet implemented).

        Returns:
            Dictionary with 'nodes' list containing node data.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service, get_silo_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        if isinstance(node_ids, str):
            node_ids = [node_ids]

        resolved_silo_id = derive_silo_id(auth.org_id)
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err

        nodes_out: list[dict[str, Any]] = []
        for nid in node_ids:
            try:
                node_uuid = uuid.UUID(nid)
            except ValueError:
                nodes_out.append({"error": "invalid_node_id", "node_id": nid})
                continue

            node = await ctx_svc.get(node_uuid, resolved_silo_id)
            if node is None:
                nodes_out.append(
                    {
                        "error": "node_not_found",
                        "node_id": nid,
                        "message": "Node may have been deleted or the silo_id is wrong.",
                    }
                )
            else:
                nodes_out.append(
                    {
                        "node_id": str(node.id),
                        "content": node.content,
                        "type": node.type,
                        "silo_id": str(node.silo_id) if node.silo_id else None,
                        "properties": node.properties,
                        "source_uri": node.source_uri,
                        "content_hash": node.content_hash,
                    }
                )

        return {"nodes": nodes_out}
