"""Tests for context_recall tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

_QUERY_RESULT = {
    "results": [],
    "total_candidates": 0,
    "search_time_ms": 5,
    "search_mode": "hybrid",
    "reflection_suggested": False,
    "metadata": {},
}

_GET_RESULT = {"nodes": []}

_GRAPH_RESULT = {
    "nodes": [],
    "edges": [],
    "traversal_stats": {"depth_reached": 1, "nodes_visited": 0, "edges_traversed": 0},
    "metadata": {},
}


@pytest.fixture
def mock_query():
    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=_QUERY_RESULT,
    ) as m:
        yield m


@pytest.fixture
def mock_get():
    with patch(
        "context_service.mcp.tools.context_recall._context_get",
        new_callable=AsyncMock,
        return_value=_GET_RESULT,
    ) as m:
        yield m


@pytest.fixture
def mock_graph():
    with patch(
        "context_service.mcp.tools.context_recall._context_graph",
        new_callable=AsyncMock,
        return_value=_GRAPH_RESULT,
    ) as m:
        yield m


@pytest.mark.asyncio
async def test_recall_query_flat(mock_query):
    from context_service.mcp.tools.context_recall import _context_recall

    result = await _context_recall(silo_id=_SILO_ID, query="some query", depth=0)

    assert "results" in result
    mock_query.assert_called_once()


@pytest.mark.asyncio
async def test_recall_query_with_depth(mock_graph):
    from context_service.mcp.tools.context_recall import _context_recall

    result = await _context_recall(silo_id=_SILO_ID, query="some query", depth=2)

    assert "nodes" in result
    mock_graph.assert_called_once()
    call_kwargs = mock_graph.call_args
    assert call_kwargs.kwargs.get("query") == "some query" or call_kwargs.args[1] == "some query"


@pytest.mark.asyncio
async def test_recall_node_ids_flat(mock_get):
    from context_service.mcp.tools.context_recall import _context_recall

    node_id = str(uuid.uuid4())
    result = await _context_recall(silo_id=_SILO_ID, node_ids=[node_id], depth=0)

    assert "nodes" in result
    mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_recall_node_ids_with_depth(mock_graph):
    from context_service.mcp.tools.context_recall import _context_recall

    node_id = str(uuid.uuid4())
    result = await _context_recall(silo_id=_SILO_ID, node_ids=[node_id], depth=1)

    assert "nodes" in result
    mock_graph.assert_called_once()


@pytest.mark.asyncio
async def test_recall_missing_input():
    from context_service.mcp.tools.context_recall import _context_recall

    result = await _context_recall(silo_id=_SILO_ID)

    assert result["error"] == "missing_input"


@pytest.mark.asyncio
async def test_recall_passes_layers_to_query(mock_query):
    from context_service.mcp.tools.context_recall import _context_recall

    await _context_recall(silo_id=_SILO_ID, query="test", layers=["memory"], depth=0)

    _, kwargs = mock_query.call_args
    assert kwargs.get("layers") == ["memory"] or mock_query.call_args.kwargs.get("layers") == ["memory"]


@pytest.mark.asyncio
async def test_recall_passes_top_k_to_query(mock_query):
    from context_service.mcp.tools.context_recall import _context_recall

    await _context_recall(silo_id=_SILO_ID, query="test", top_k=5, depth=0)

    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args.kwargs
    assert call_kwargs.get("top_k") == 5
