"""Tests for MCP tool registry."""

from context_service.mcp.tools.registry import get_profile_tools, load_tool_config


def test_load_tool_config_returns_dict():
    config = load_tool_config()
    assert isinstance(config, dict)
    assert "profiles" in config
    assert "tools" in config
    assert "mcp_instructions" in config


def test_standard_profile_has_six_tools():
    config = load_tool_config()
    assert len(config["profiles"]["standard"]) == 6
    assert "remember" in config["profiles"]["standard"]
    assert "learn" in config["profiles"]["standard"]
    assert "believe" in config["profiles"]["standard"]
    assert "recall" in config["profiles"]["standard"]
    assert "trace" in config["profiles"]["standard"]
    assert "link" in config["profiles"]["standard"]


def test_reasoning_profile_has_eleven_tools():
    config = load_tool_config()
    assert len(config["profiles"]["reasoning"]) == 11


def test_get_profile_tools_standard():
    tools = get_profile_tools("standard")
    assert len(tools) == 7  # 6 + patterns (always available)
    assert "patterns" in tools


def test_get_profile_tools_invalid_profile_returns_standard():
    tools = get_profile_tools("invalid")
    assert len(tools) == 7  # falls back to standard
