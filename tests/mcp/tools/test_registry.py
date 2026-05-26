"""Tests for MCP tool registry."""

from context_service.mcp.tools.registry import load_tool_config


def test_load_tool_config_returns_dict():
    config = load_tool_config()
    assert isinstance(config, dict)
    assert "tools" in config
    assert "mcp_instructions" in config


def test_config_has_all_expected_tools():
    config = load_tool_config()
    expected = {
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
        "forget",
        "patterns",
        "dismiss",
        "tick",
    }
    assert expected == set(config["tools"].keys())
