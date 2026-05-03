"""MCP tool: context_admin - Admin and utility actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from context_service.mcp.tools.context_close_reasoning import _context_close_reasoning
from context_service.mcp.tools.context_graph import _context_graph
from context_service.mcp.tools.context_history import _context_history
from context_service.mcp.tools.silo import _silo_list_impl
from context_service.services.models import derive_silo_id

if TYPE_CHECKING:
    from fastmcp import FastMCP

_VALID_ACTIONS = ("silo_list", "close_session", "provenance", "history")


async def _context_admin(
    action: str,
    silo_id: str,
    ref: str | None = None,
    name: str | None = None,  # noqa: ARG001
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if action == "silo_list":
        return await _silo_list_impl()

    if action == "close_session":
        if not ref:
            return {"error": "missing_ref", "message": "ref (chain_id) required for close_session"}
        return await _context_close_reasoning(silo_id=silo_id, chain_id=ref)

    if action == "provenance":
        if not ref:
            return {"error": "missing_ref", "message": "ref (node_id) required for provenance"}
        return await _context_graph(silo_id=silo_id, seed_nodes=[ref], mode="provenance")

    if action == "history":
        if not ref:
            return {"error": "missing_ref", "message": "ref (node_id or subject) required for history"}
        return await _context_history(silo_id=silo_id, node_id=ref)

    return {"error": "unknown_action", "valid": list(_VALID_ACTIONS)}


def register(mcp: FastMCP) -> None:
    """Register the context_admin tool."""

    @mcp.tool(
        name="context_admin",
        description=(
            "Admin and utility actions: silo_list, close_session, provenance, history. "
            "silo_list: list org silos. "
            "close_session: close a reasoning chain (ref=chain_id). "
            "provenance: trace citation chain for a node (ref=node_id). "
            "history: show belief evolution for a node (ref=node_id or subject)."
        ),
    )
    async def context_admin(
        action: Literal["silo_list", "close_session", "provenance", "history"],
        ref: str | None = None,
        name: str | None = None,
        silo_id: str | None = None,
    ) -> dict[str, Any]:
        """Admin and utility actions.

        Args:
            action: silo_list|close_session|provenance|history.
            ref: Node ID for provenance/history, chain_id for close_session.
            name: Reserved for future use.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.

        Returns:
            Action-specific response dict.
        """
        from context_service.mcp.server import get_mcp_auth_context

        auth = await get_mcp_auth_context()
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        return await _context_admin(
            action=action,
            silo_id=resolved_silo_id,
            ref=ref,
            name=name,
        )
