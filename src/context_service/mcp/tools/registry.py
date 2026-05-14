"""MCP tool registry - loads tool config from YAML and registers dynamically."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

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

    with open(_CONFIG_PATH) as f:
        _cached_config = yaml.safe_load(f)

    logger.info("mcp_tool_config_loaded", path=str(_CONFIG_PATH))
    return _cached_config


def get_profile_tools(profile: str) -> list[str]:
    """Get list of tool names for a profile, including always-available tools.

    Args:
        profile: Profile name (standard, reasoning). Falls back to standard if invalid.

    Returns:
        List of tool names to register.
    """
    config = load_tool_config()

    if profile not in config["profiles"]:
        logger.warning("invalid_mcp_profile", profile=profile, fallback="standard")
        profile = "standard"

    tools = list(config["profiles"][profile])

    # Add always-available tools
    for name, tool_def in config["tools"].items():
        if tool_def.get("always_available") and name not in tools:
            tools.append(name)

    return tools


def get_tool_description(tool_name: str) -> str:
    """Get description for a tool from config."""
    config = load_tool_config()
    return str(config["tools"].get(tool_name, {}).get("description", ""))


def get_mcp_instructions() -> str:
    """Get MCP server instructions from config."""
    config = load_tool_config()
    return str(config.get("mcp_instructions", ""))


def register_profile_tools(mcp: FastMCP, profile: str = "standard") -> None:
    """Register all tools for a profile.

    Args:
        mcp: FastMCP server instance.
        profile: Tool profile (standard or reasoning).

    Note: Imports are inside function to avoid circular imports,
    since tool modules import from registry.
    """
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

    tool_registers = {
        "remember": remember.register,
        "learn": learn.register,
        "believe": believe.register,
        "recall": recall.register,
        "trace": trace.register,
        "link": link.register,
        "reason": reason.register,
        "reflect": reflect.register,
        "hypothesize": hypothesize.register,
        "revise": revise.register,
        "commit": commit.register,
        "patterns": patterns.register,
    }

    tool_names = get_profile_tools(profile)

    for name in tool_names:
        if name in tool_registers:
            tool_registers[name](mcp)
            logger.debug("mcp_tool_registered", tool=name, profile=profile)
        else:
            logger.warning("mcp_tool_not_found", tool=name)

    logger.info(
        "mcp_profile_tools_registered",
        profile=profile,
        tool_count=len(tool_names),
    )
