# tests/mcp/tools/test_trace.py
"""Tests for trace tool."""

from unittest.mock import AsyncMock

import pytest

from context_service.mcp.tools.trace import _trace_impl
from context_service.services.context_meta import ProvenanceResult, ProvenanceStep


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


@pytest.mark.asyncio
async def test_trace_marks_stub_nodes(mock_mcp_context, mock_context_service):
    """trace should include stub=True for pruned interior nodes and stub=False for live nodes."""
    live_step = ProvenanceStep(
        node_id="live-node",
        layer="knowledge",
        relationship="DERIVED_FROM",
        confidence=0.9,
        stub=False,
    )
    stub_step = ProvenanceStep(
        node_id="stub-node",
        layer="knowledge",
        relationship="DERIVED_FROM",
        confidence=1.0,
        stub=True,
    )
    mock_context_service.provenance = AsyncMock(
        return_value=ProvenanceResult(
            chain=[live_step, stub_step],
            root_sources=[],
        )
    )

    result = await _trace_impl(node_id="test-node-id")

    assert "chain" in result
    chain = result["chain"]
    assert len(chain) == 2

    live_entry = next(e for e in chain if e["node_id"] == "live-node")
    assert live_entry["stub"] is False

    stub_entry = next(e for e in chain if e["node_id"] == "stub-node")
    assert stub_entry["stub"] is True
