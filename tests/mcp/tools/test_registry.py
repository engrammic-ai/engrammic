"""Tests for MCP tool registry."""

from context_service.mcp.tools.registry import (
    get_profile_tools,
    get_tool_description,
    load_tool_config,
)


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


def test_reasoning_profile_includes_all_expected_tools():
    """Reasoning profile includes standard tools plus reasoning-specific verbs."""
    config = load_tool_config()
    reasoning_tools = set(config["profiles"]["reasoning"])
    standard_tools = set(config["profiles"]["standard"])

    # Reasoning should be a superset of standard
    assert standard_tools.issubset(reasoning_tools)

    # Must include these reasoning-specific tools
    expected_extras = {"reason", "reflect", "hypothesize", "revise", "commit", "accept", "reject", "forget"}
    assert expected_extras.issubset(reasoning_tools), f"Missing: {expected_extras - reasoning_tools}"


def test_get_profile_tools_standard():
    tools = get_profile_tools("standard")
    assert len(tools) == 7  # 6 + patterns (always available)
    assert "patterns" in tools


def test_get_profile_tools_invalid_profile_returns_standard():
    tools = get_profile_tools("invalid")
    assert len(tools) == 7  # falls back to standard


def test_accept_in_reasoning_profile() -> None:
    """accept verb is part of the reasoning profile."""
    tools = get_profile_tools("reasoning")
    assert "accept" in tools, f"accept not in reasoning profile. Got: {tools}"


def test_reject_in_reasoning_profile() -> None:
    """reject verb is part of the reasoning profile."""
    tools = get_profile_tools("reasoning")
    assert "reject" in tools


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
