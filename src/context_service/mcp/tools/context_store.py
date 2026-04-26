# context_service/mcp/tools/context_store.py
"""MCP tool: context_store - Store context node."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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
            Dictionary with node_id, content, type, silo_id, and created_at.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_context_service

        auth = get_mcp_auth()
        service = get_context_service()

        # TODO: Implement when ContextService is ported
        # For now, this serves as the interface contract
        raise NotImplementedError(
            f"context_store not yet implemented. "
            f"org_id={auth.org_id}, silo_id={silo_id}, type={type}, "
            f"content_len={len(content)}"
        )
