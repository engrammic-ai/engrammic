"""MCP tool registry - loads tool config from YAML and registers dynamically."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from context_service.config.paths import resolve_config_file

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = structlog.get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "mcp_tools.yaml"
_cached_config: dict[str, Any] | None = None


def load_tool_config() -> dict[str, Any]:
    """Load tool configuration from YAML file.

    Returns cached config on subsequent calls.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    path = resolve_config_file("mcp_tools.yaml", _CONFIG_PATH)
    with open(path) as f:
        _cached_config = yaml.safe_load(f)

    logger.info("mcp_tool_config_loaded", path=str(path))
    return _cached_config


def get_tool_description(tool_name: str) -> str:
    """Get description for a tool from config."""
    config = load_tool_config()
    tool = config.get("tools", {}).get(tool_name)
    if tool:
        return str(tool.get("description", ""))
    return ""


def get_mcp_instructions() -> str:
    """Get MCP server instructions from config."""
    config = load_tool_config()
    return str(config.get("mcp_instructions", ""))


def register_tools(mcp: FastMCP) -> None:
    """Register MCP tools.

    CITE v2 minimal surface (6 tools):
        remember, learn, recall, trace, forget, tick

    Extended tools (not exposed by default, enable via config):
        decide, accept, hypothesize, revise, commit, dismiss,
        link, reason, reflect, history, patterns

    The minimal surface compensates by enhancing recall/trace output:
        - recall: includes hints, provenance metadata, conflict status
        - trace: walks full provenance chains with layer info
    See context/specs/2026-06-18-coherence-layer-v2.md for details.

    Args:
        mcp: FastMCP server instance.

    Note: Imports are inside function to avoid circular imports,
    since tool modules import from registry.
    """
    from context_service.mcp.tools import (
        forget,
        learn,
        recall,
        remember,
        tick,
        trace,
        update,
    )

    tools = {
        "remember": remember.register,
        "learn": learn.register,
        "recall": recall.register,
        "trace": trace.register,
        "forget": forget.register,
        "tick": tick.register,
        "update": update.register,
    }

    for name, register_fn in tools.items():
        register_fn(mcp)
        logger.debug("mcp_tool_registered", tool=name)

    logger.info("mcp_tools_registered", tool_count=len(tools))
