# src/context_service/mcp/tools/__init__.py
"""MCP tool implementations -- intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Intent-based tools (external-facing)
from context_service.mcp.tools import (
    believe,
    commit,
    hypothesize,
    learn,
    link,
    patterns,
    reason,
    recall,
    reflect,
    remember,
    revise,
    trace,
)

# Internal-only tools (not registered via registry)
from context_service.mcp.tools.context_accept_belief import register as register_accept_belief
from context_service.mcp.tools.context_admin import register as register_admin
from context_service.mcp.tools.context_belief_state import register as register_belief_state
from context_service.mcp.tools.context_reject_belief import register as register_reject_belief

# Registry for profile-based registration
from context_service.mcp.tools.registry import register_profile_tools


def register_all(mcp: FastMCP, profile: str = "standard") -> None:
    """Register all MCP tools for the given profile.

    This is the main entry point. Use this instead of individual registers.
    """
    register_profile_tools(mcp, profile)


def register_internal_tools(mcp: FastMCP) -> None:
    """Register internal-only tools (for SAGE and admin use).

    These are NOT included in the standard/reasoning profiles.
    Call separately if needed.
    """
    register_admin(mcp)
    register_accept_belief(mcp)
    register_reject_belief(mcp)
    register_belief_state(mcp)


__all__ = [
    "register_all",
    "register_internal_tools",
    "register_profile_tools",
    # Individual tool modules
    "remember",
    "learn",
    "believe",
    "recall",
    "trace",
    "link",
    "reason",
    "reflect",
    "hypothesize",
    "revise",
    "commit",
    "patterns",
]
