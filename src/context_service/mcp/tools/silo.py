# context_service/mcp/tools/silo.py
"""MCP tools: silo_list - Silo management (1:1 org-to-silo model)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.mcp.server import get_mcp_auth_context, get_silo_service
from context_service.services.silo import ensure_silo

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _silo_list_impl() -> dict[str, Any]:
    """Internal implementation for silo_list (testable)."""
    auth = await get_mcp_auth_context()
    silo_svc = get_silo_service()

    silo = await ensure_silo(silo_svc, org_id=auth.org_id)

    return {
        "silos": [
            {
                "silo_id": str(silo.id),
                "name": silo.name,
                "org_id": silo.org_id,
                "description": silo.description,
                "dissolvability": silo.dissolvability,
            }
        ],
    }


def register_silo_list(mcp: FastMCP) -> None:
    """Register the silo_list tool on the MCP server."""

    @mcp.tool(
        name="silo_list",
        description="Get the silo for the current org. Auto-creates if first use.",
    )
    async def silo_list() -> dict[str, Any]:
        """Get the org's silo (auto-created on first use).

        MVP model: each org has exactly one silo. Multi-silo support
        is planned for v1.5.

        Returns:
            Dictionary with 'silos' list (always length 1).
        """
        return await _silo_list_impl()
