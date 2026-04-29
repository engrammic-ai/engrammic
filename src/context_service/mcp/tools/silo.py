# context_service/mcp/tools/silo.py
"""MCP tools: silo_create, silo_list - Silo management."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_silo_create(mcp: FastMCP) -> None:
    """Register the silo_create tool on the MCP server."""

    @mcp.tool(
        name="silo_create",
        description="Create a new organizational silo for context isolation.",
    )
    async def silo_create(
        name: str,
        description: str | None = None,
        dissolvability: float = 0.5,
    ) -> dict[str, Any]:
        """Create a new silo.

        Args:
            name: Silo name.
            description: Optional description.
            dissolvability: Cross-silo traversal permeability (0.0=isolated, 1.0=open).

        Returns:
            Dictionary with silo details.
        """
        from context_service.mcp.server import get_mcp_auth_context, get_silo_service

        auth = await get_mcp_auth_context()
        silo_svc = get_silo_service()

        silo = await silo_svc.get_or_create(
            name=name,
            org_id=auth.org_id,
            description=description,
            dissolvability=dissolvability,
        )

        return {
            "silo_id": str(silo.id),
            "name": silo.name,
            "org_id": silo.org_id,
            "description": silo.description,
            "dissolvability": silo.dissolvability,
        }


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
