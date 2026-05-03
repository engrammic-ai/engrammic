"""MCP tool: context_get_reflections - Retrieve meta-observations about a node."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_context_service, get_mcp_auth_context
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _context_get_reflections(
    silo_id: str,
    node_id: str,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    from context_service.mcp.server import get_silo_service
    from context_service.services.silo import validate_silo_ownership

    auth = await get_mcp_auth_context()

    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err

    expected_silo_id = derive_silo_id(auth.org_id)

    if not node_id or not node_id.strip():
        return {"error": "missing_node_id", "message": "node_id is required"}

    ctx_svc = get_context_service()
    reflections = await ctx_svc.get_reflections(
        silo_id=str(expected_silo_id),
        node_id=node_id,
    )

    return {
        "node_id": node_id,
        "reflections": reflections,
        "count": len(reflections),
    }


def register(mcp: FastMCP) -> None:
    """Register the context_get_reflections tool."""

    @mcp.tool(
        name="context_get_reflections",
        description=(
            "Retrieve meta-observations (reflections) about a node. "
            "Returns MetaObservations linked via ABOUT edges. "
            "Use to see what an agent has noted about a belief or fact."
        ),
    )
    async def context_get_reflections(
        node_id: str,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Get reflections about a node.

        Args:
            node_id: The node to get reflections for.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            {node_id, reflections, count}
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_get_reflections(
            silo_id=resolved_silo_id,
            node_id=node_id,
        )
