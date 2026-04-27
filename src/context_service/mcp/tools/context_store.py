# context_service/mcp/tools/context_store.py
"""MCP tool: context_store - Store context node."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from context_service.services.models import ScopeContext, derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    """Register the context_store tool on the MCP server."""

    @mcp.tool(
        name="context_store",
        description=(
            "Store a context node with automatic embedding generation. "
            "Returns the created node with its ID for future retrieval. "
            "Requires silo_id to specify which silo to store in."
        ),
    )
    async def context_store(
        content: str,
        type: str,
        silo_id: str,
        properties: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Store a new context node.

        Args:
            content: The text content to store.
            type: Node type (e.g. document, decision, observation).
            silo_id: UUID of the silo to store in.
            properties: Optional metadata dictionary.
            idempotency_key: Optional key for deduplication.

        Returns:
            Dictionary with node_id, status, and embedding_status.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        ctx_svc = get_context_service()

        expected_silo_id = derive_silo_id(auth.org_id)
        try:
            requested = uuid.UUID(silo_id)
        except ValueError:
            return {"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"}

        if requested != expected_silo_id:
            return {
                "error": "silo_not_found",
                "silo_id": silo_id,
                "message": "Silo does not exist or org_id mismatch.",
            }

        scope = ScopeContext(org_id=auth.org_id, silo_id=expected_silo_id)
        node = await ctx_svc.store(
            scope=scope,
            content=content,
            node_type=type,
            properties=properties,
            idempotency_key=idempotency_key,
        )

        return {
            "node_id": str(node.id),
            "status": "created",
            "embedding_status": "indexed",
            "extraction_queued": False,
        }
