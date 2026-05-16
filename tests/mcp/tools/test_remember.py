# tests/mcp/tools/test_remember.py
"""Tests for remember tool."""

import pytest

from context_service.mcp.tools.remember import _remember_impl


@pytest.mark.asyncio
async def test_remember_returns_node_id(mock_mcp_context, mock_context_service):
    """remember should return node_id and created_at."""
    result = await _remember_impl(
        content="Test observation",
        tags=["test"],
        decay="standard",
    )

    assert "node_id" in result
    assert "created_at" in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_remember_invalid_decay_returns_error(mock_mcp_context):
    """remember should return error for invalid decay class."""
    result = await _remember_impl(
        content="Test",
        decay="invalid_decay",
    )

    assert "error" in result
    assert result["error"] == "invalid_decay_class"
