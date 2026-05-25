"""Tests for MCP tool registry."""

from context_service.mcp.tools.registry import (
    get_tool_description,
    load_tool_config,
)


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
        "accept",
        "reject",
        "forget",
        "patterns",
        "dismiss",
        "tick",
    }
    assert expected == set(config["tools"].keys())


def test_accept_description_present() -> None:
    """accept tool has a non-empty description."""
    desc = get_tool_description("accept")
    assert desc, "accept description is empty"
    assert "ProposedBelief" in desc or "synthesized" in desc.lower()


def test_reject_description_present() -> None:
    """reject tool has a non-empty description mentioning ProposedBelief."""
    desc = get_tool_description("reject")
    assert desc, "reject description is empty"
    assert "ProposedBelief" in desc or "tombstone" in desc.lower() or "rejected" in desc.lower()
