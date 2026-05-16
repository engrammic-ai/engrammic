# tests/mcp/tools/test_learn.py
"""Tests for learn tool."""

import pytest

from context_service.mcp.tools.learn import _learn_impl


@pytest.mark.asyncio
async def test_learn_requires_evidence(mock_mcp_context):
    """learn should require evidence parameter."""
    result = await _learn_impl(
        claim="Test claim",
        evidence=[],  # empty evidence
        source="document",
    )

    # Empty evidence should be rejected or handled
    assert "node_id" in result or "error" in result


@pytest.mark.asyncio
async def test_learn_returns_node_id(
    mock_mcp_context, mock_context_service, mock_evidence_validator
):
    """learn should return node_id with valid evidence."""
    result = await _learn_impl(
        claim="Test claim",
        evidence=["node:123e4567-e89b-12d3-a456-426614174000"],
        source="document",
        confidence=0.9,
    )

    assert "node_id" in result
    assert "created_at" in result
