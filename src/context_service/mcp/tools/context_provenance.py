"""MCP tool: context_provenance - Trace citation chain to Memory-layer sources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_context_service, get_mcp_auth_context
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_provenance(
    silo_id: str,
    node_id: str,
    max_depth: int = 10,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.server import get_silo_service
    from context_service.services.silo import validate_silo_ownership

    auth = get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not node_id or not node_id.strip():
        return {"error": "missing_node_id", "message": "node_id is required"}

    ctx_svc = get_context_service()
    result = await ctx_svc.provenance(
        silo_id=str(expected_silo_id),
        node_id=node_id,
        max_depth=max_depth,
    )

    return {
        "node_id": node_id,
        "chain": [
            {
                "node_id": step.node_id,
                "layer": step.layer,
                "relationship": step.relationship,
                "confidence": step.confidence,
            }
            for step in result.chain
        ],
        "root_sources": result.root_sources,
        "chain_length": len(result.chain),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_provenance tool."""

    @mcp.tool(
        name="context_provenance",
        description=(
            "Trace the citation chain from a node back to its Memory-layer sources. "
            "Follows DERIVED_FROM, PROMOTED_FROM, and SYNTHESIZED_FROM edges. "
            "Use to audit where a belief or fact originated."
        ),
    )
    async def context_provenance(
        silo_id: str,
        node_id: str,
        max_depth: int = 10,
    ) -> dict[str, Any]:
        """Trace citation chain to source.

        Args:
            silo_id: UUID of the silo.
            node_id: The node to trace provenance for.
            max_depth: Maximum edges to follow (default 10).

        Returns:
            {node_id, chain, root_sources, chain_length}
        """
        return await _context_provenance(
            silo_id=silo_id,
            node_id=node_id,
            max_depth=max_depth,
        )
