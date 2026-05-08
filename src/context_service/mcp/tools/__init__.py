# context_service/mcp/tools/__init__.py
"""MCP tool implementations -- EAG intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

from context_service.mcp.tools import context_skills
from context_service.mcp.tools.context_accept_belief import register as register_accept_belief
from context_service.mcp.tools.context_admin import register as register_admin
from context_service.mcp.tools.context_belief_state import register as register_belief_state
from context_service.mcp.tools.context_crystallize import register as register_crystallize
from context_service.mcp.tools.context_link import register as register_link
from context_service.mcp.tools.context_recall import register as register_recall
from context_service.mcp.tools.context_reject_belief import register as register_reject_belief
from context_service.mcp.tools.context_skills import register as register_skills
from context_service.mcp.tools.context_store import register as register_store
from context_service.mcp.tools.context_update_belief import register as register_update_belief


def register_all(mcp: FastMCP) -> None:
    """Register all EAG MCP tools."""
    register_store(mcp)
    register_recall(mcp)
    register_admin(mcp)
    register_link(mcp)
    register_belief_state(mcp)
    register_update_belief(mcp)
    register_crystallize(mcp)
    register_accept_belief(mcp)
    register_reject_belief(mcp)

    from context_service.mcp.server import get_skill_service

    try:
        skill_svc = get_skill_service()
        register_skills(mcp, skill_svc)
    except RuntimeError:
        pass  # SkillService not configured (no db_session); skip tool registration


__all__ = [
    "register_all",
    "context_skills",
    "register_skills",
    "register_accept_belief",
    "register_admin",
    "register_belief_state",
    "register_crystallize",
    "register_link",
    "register_recall",
    "register_reject_belief",
    "register_store",
    "register_update_belief",
]
