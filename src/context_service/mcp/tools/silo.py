# context_service/mcp/tools/silo.py
"""MCP tools: silo_list - Silo management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_silo_list(mcp: FastMCP) -> None:
    """Register the silo_list tool on the MCP server."""

    @mcp.tool(
        name="silo_list",
        description="List all silos for the current tenant.",
    )
    async def silo_list() -> dict[str, Any]:
        """List all available silos.

        Returns:
            Dictionary with 'silos' list.
        """
        from context_service.mcp.server import get_mcp_auth_context, get_silo_service

        auth = await get_mcp_auth_context()
        silo_svc = get_silo_service()

        silos = await silo_svc.list(org_id=auth.org_id)

        return {
            "silos": [
                {
                    "silo_id": str(s.id),
                    "name": s.name,
                    "org_id": s.org_id,
                    "description": s.description,
                    "dissolvability": s.dissolvability,
                }
                for s in silos
            ],
        }
