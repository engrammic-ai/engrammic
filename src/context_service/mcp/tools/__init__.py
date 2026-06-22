# src/context_service/mcp/tools/__init__.py
"""MCP tool implementations -- intent-based surface."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

# Intent-based tools (external-facing)
from context_service.mcp.tools import (
    accept,
    commit,
    decide,
    dismiss,
    forget,
    learn,
    patterns,
    recall,
    remember,
    revise,
    tick,
    trace,
    update,
)

# Registry
from context_service.mcp.tools.registry import register_tools


def register_all(mcp: FastMCP) -> None:
    """Register all MCP tools.

    This is the main entry point. Use this instead of individual registers.
    """
    register_tools(mcp)


__all__ = [
    "register_all",
    "register_tools",
    # Individual tool modules (deprecated tools still importable but not registered)
    "accept",
    "commit",
    "decide",
    "dismiss",
    "forget",
    "learn",
    "patterns",
    "recall",
    "remember",
    "revise",
    "tick",
    "trace",
    "update",
]
