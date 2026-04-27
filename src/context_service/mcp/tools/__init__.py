# context_service/mcp/tools/__init__.py
"""MCP tool implementations — EAG intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Write tools (intent verbs)
from context_service.mcp.tools.context_assert import register as register_assert
from context_service.mcp.tools.context_commit import register as register_commit
from context_service.mcp.tools.context_get import register as register_get
from context_service.mcp.tools.context_graph import register as register_graph
from context_service.mcp.tools.context_history import register as register_history
from context_service.mcp.tools.context_link import register as register_link

# Meta-memory tools
from context_service.mcp.tools.context_provenance import register as register_provenance

# Read tools
from context_service.mcp.tools.context_query import register as register_query

# Intelligence tools
from context_service.mcp.tools.context_reason import register as register_reason
from context_service.mcp.tools.context_reflect import register as register_reflect
from context_service.mcp.tools.context_remember import register as register_remember

# Silo management
from context_service.mcp.tools.silo import register_silo_create, register_silo_list


def register_all(mcp: FastMCP) -> None:
    """Register all EAG MCP tools."""
    # Write tools
    register_remember(mcp)
    register_assert(mcp)
    register_commit(mcp)
    register_reflect(mcp)
    register_link(mcp)

    # Read tools
    register_query(mcp)
    register_get(mcp)
    register_graph(mcp)

    # Meta-memory tools
    register_provenance(mcp)
    register_history(mcp)

    # Intelligence tools
    register_reason(mcp)

    # Silo management
    register_silo_create(mcp)
    register_silo_list(mcp)


__all__ = [
    "register_all",
    "register_remember",
    "register_assert",
    "register_commit",
    "register_reflect",
    "register_link",
    "register_query",
    "register_get",
    "register_graph",
    "register_provenance",
    "register_history",
    "register_reason",
    "register_silo_create",
    "register_silo_list",
]
