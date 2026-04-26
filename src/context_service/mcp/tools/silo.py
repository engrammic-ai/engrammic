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
        description: str | None = None,  # noqa: ARG001
        dissolvability: float = 0.5,  # noqa: ARG001
    ) -> dict[str, Any]:
        """Create a new silo.

        Args:
            name: Silo name.
            description: Optional description.
            dissolvability: Cross-silo traversal permeability (0.0=isolated, 1.0=open).

        Returns:
            Dictionary with silo details.
        """
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_silo_service

        auth = get_mcp_auth()
        get_silo_service()

        # TODO: Implement when SiloService is ported
        raise NotImplementedError(
            f"silo_create not yet implemented. org_id={auth.org_id}, name={name}"
        )


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
        from context_service.mcp.auth import get_mcp_auth
        from context_service.mcp.server import get_silo_service

        auth = get_mcp_auth()
        get_silo_service()

        # TODO: Implement when SiloService is ported
        raise NotImplementedError(f"silo_list not yet implemented. org_id={auth.org_id}")
