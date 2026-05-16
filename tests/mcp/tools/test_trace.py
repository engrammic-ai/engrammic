# tests/mcp/tools/test_trace.py
"""Tests for trace tool."""

import pytest

from context_service.mcp.tools.trace import _trace_impl


@pytest.mark.asyncio
async def test_trace_requires_node_id(mock_mcp_context):
    """trace should require node_id parameter."""
    result = await _trace_impl(node_id="")

    assert "error" in result


@pytest.mark.asyncio
async def test_trace_returns_chain(mock_mcp_context, mock_context_service):
    """trace should return provenance chain."""
    result = await _trace_impl(node_id="test-node-id")

    assert "chain" in result
    assert "root_sources" in result
