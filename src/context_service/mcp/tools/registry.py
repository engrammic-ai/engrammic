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
    """Get description for a tool from config.

    Checks active tools first, then deprecated_tools for backward compatibility.
    """
    config = load_tool_config()
    active = config.get("tools", {}).get(tool_name)
    if active:
        return str(active.get("description", ""))
    deprecated = config.get("deprecated_tools", {}).get(tool_name)
    if deprecated:
        return str(deprecated.get("description", ""))
    return ""


def get_mcp_instructions() -> str:
    """Get MCP server instructions from config."""
    config = load_tool_config()
    return str(config.get("mcp_instructions", ""))


def register_tools(mcp: FastMCP) -> None:
    """Register all MCP tools.

    CITE v2 active surface: remember, learn, recall, trace, forget, tick.
    Deprecated tools are still registered for backward compatibility but
    agents should not use them for new work. See mcp_tools.yaml for details.

    Args:
        mcp: FastMCP server instance.

    Note: Imports are inside function to avoid circular imports,
    since tool modules import from registry.
    """
    from context_service.mcp.tools import (
        accept,
        commit,
        decide,
        dismiss,
        forget,
        history,
        hypothesize,
        learn,
        link,
        patterns,
        reason,
        recall,
        reflect,
        remember,
        revise,
        tick,
        trace,
    )

    # Active v2 tools
    active_registers = {
        "remember": remember.register,
        "learn": learn.register,
        "recall": recall.register,
        "trace": trace.register,
        "forget": forget.register,
        "tick": tick.register,
    }

    # Deprecated tools kept for backward compatibility
    deprecated_registers = {
        "decide": decide.register,
        "accept": accept.register,
        "dismiss": dismiss.register,
        "hypothesize": hypothesize.register,
        "revise": revise.register,
        "commit": commit.register,
        "reason": reason.register,
        "reflect": reflect.register,
        "link": link.register,
        "history": history.register,
        "patterns": patterns.register,
    }

    for name, register_fn in active_registers.items():
        register_fn(mcp)
        logger.debug("mcp_tool_registered", tool=name)

    for name, register_fn in deprecated_registers.items():
        register_fn(mcp)
        logger.debug("mcp_tool_registered", tool=name, deprecated=True)

    total = len(active_registers) + len(deprecated_registers)
    logger.info(
        "mcp_tools_registered",
        tool_count=total,
        active_count=len(active_registers),
        deprecated_count=len(deprecated_registers),
    )
