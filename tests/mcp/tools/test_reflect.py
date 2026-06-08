# tests/mcp/tools/test_reflect.py
"""Tests for reflect tool."""

from unittest.mock import AsyncMock, patch

import pytest

from context_service.mcp.tools.reflect import _reflect_impl


@pytest.mark.asyncio
async def test_reflect_returns_node_id(mock_mcp_context, mock_context_service):
    """reflect should return node_id, observation_type, about_nodes, and created_at."""
    result = await _reflect_impl(
        observation="I noticed a contradiction in how auth is handled",
        type="contradiction",
        about=["node-abc"],
        confidence=0.8,
    )

    assert "node_id" in result
    assert "created_at" in result
    assert result.get("error") is None


@pytest.mark.asyncio
async def test_reflect_with_affected_nodes(mock_mcp_context, mock_context_service):
    """reflect should include about_nodes in the response matching the input."""
    about = ["node-111", "node-222", "node-333"]
    result = await _reflect_impl(
        observation="These three nodes form a consistent pattern",
        type="pattern",
        about=about,
    )

    assert "about_nodes" in result
    assert result["about_nodes"] == about
    assert result.get("observation_type") == "pattern"


@pytest.mark.asyncio
async def test_reflect_observation_type_in_response(mock_mcp_context, mock_context_service):
    """reflect should echo observation_type back in the response."""
    for obs_type in ("pattern", "contradiction", "uncertainty", "drift"):
        result = await _reflect_impl(
            observation=f"Test observation of type {obs_type}",
            type=obs_type,
            about=["node-xyz"],
        )

        assert result.get("observation_type") == obs_type


@pytest.mark.asyncio
async def test_reflect_store_error_propagates(mock_mcp_context, mock_context_service):
    """reflect should propagate errors raised by the underlying store."""
    with (
        patch(
            "context_service.mcp.tools.context_store.store_memory",
            new=AsyncMock(side_effect=RuntimeError("store unavailable")),
        ),
        pytest.raises(RuntimeError, match="store unavailable"),
    ):
        await _reflect_impl(
            observation="This should fail",
            type="uncertainty",
            about=["node-fail"],
        )
