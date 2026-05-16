# tests/mcp/tools/test_believe.py
"""Tests for believe tool."""

import pytest

from context_service.mcp.tools.believe import _believe_impl


@pytest.mark.asyncio
async def test_believe_requires_about(mock_mcp_context):
    """believe should require about parameter."""
    result = await _believe_impl(
        belief="Test belief",
        about=[],  # empty about
    )

    assert "error" in result
    assert result["error"] == "missing_about"


@pytest.mark.asyncio
async def test_believe_returns_node_id(mock_mcp_context, mock_context_service):
    """believe should return node_id with valid about."""
    result = await _believe_impl(
        belief="Test belief",
        about=["node-123"],
        confidence=0.9,
        reasoning="Based on evidence",
    )

    assert "node_id" in result
    assert "created_at" in result
