# context_service/mcp/tools/__init__.py
"""MCP tool implementations -- EAG intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

from context_service.mcp.tools.context_admin import register as register_admin
from context_service.mcp.tools.context_link import register as register_link
from context_service.mcp.tools.context_recall import register as register_recall
from context_service.mcp.tools.context_store import register as register_store


def register_all(mcp: FastMCP) -> None:
    """Register all EAG MCP tools."""
    register_store(mcp)
    register_recall(mcp)
    register_admin(mcp)
    register_link(mcp)


__all__ = [
    "register_all",
    "register_admin",
    "register_link",
    "register_recall",
    "register_store",
]
