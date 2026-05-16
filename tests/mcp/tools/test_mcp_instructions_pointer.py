"""Tests that mcp_instructions points agents at the onboarding pattern."""

from context_service.mcp.tools.registry import get_mcp_instructions


def test_instructions_point_to_onboarding_pattern():
    text = get_mcp_instructions()
    assert "patterns" in text
    assert "onboarding" in text
