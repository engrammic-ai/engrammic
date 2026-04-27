"""Tests for context_graph tool."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_deps():
    with (
        patch("context_service.mcp.tools.context_graph.get_mcp_auth") as auth_mock,
        patch("context_service.mcp.tools.context_graph.get_context_service") as svc_mock,
        patch("context_service.mcp.tools.context_graph.get_silo_service", return_value=MagicMock()),
        patch(
            "context_service.mcp.tools.context_graph.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        graph_result = MagicMock()
        graph_result.nodes = [
            {"node_id": str(uuid.uuid4()), "type": "context", "content": "Test", "layer": "memory"}
        ]
        graph_result.edges = []
        graph_result.depth_reached = 2
        graph_result.nodes_visited = 1
        graph_result.edges_traversed = 0
        svc.graph_traversal.return_value = graph_result
        svc_mock.return_value = svc

        yield {"auth": auth, "svc": svc}


@pytest.mark.asyncio
async def test_graph_with_query_seed(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="OAuth token policy",
    )

    assert "nodes" in result
    assert "edges" in result
    assert "traversal_stats" in result
    mock_deps["svc"].graph_traversal.assert_called_once()


@pytest.mark.asyncio
async def test_graph_with_seed_nodes(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    seed = [str(uuid.uuid4()), str(uuid.uuid4())]
    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        seed_nodes=seed,
    )

    assert "error" not in result
    call_kwargs = mock_deps["svc"].graph_traversal.call_args.kwargs
    assert call_kwargs["seed_nodes"] == seed


@pytest.mark.asyncio
async def test_graph_missing_seed(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
    )

    assert result["error"] == "missing_seed"


@pytest.mark.asyncio
async def test_graph_invalid_silo_id(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    with patch(
        "context_service.mcp.tools.context_graph.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "invalid_silo_id", "message": "silo_id must be a valid UUID"},
    ):
        result = await _context_graph(silo_id="not-a-uuid", query="test")

    assert result["error"] == "invalid_silo_id"


@pytest.mark.asyncio
async def test_graph_wrong_silo_id(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    with patch(
        "context_service.mcp.tools.context_graph.validate_silo_ownership",
        new_callable=AsyncMock,
        return_value={"error": "silo_not_found", "silo_id": str(uuid.uuid4())},
    ):
        result = await _context_graph(
            silo_id=str(uuid.uuid4()),
            query="test",
        )

    assert result["error"] == "silo_not_found"


@pytest.mark.asyncio
async def test_graph_invalid_max_depth(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        max_depth=10,
    )

    assert result["error"] == "invalid_max_depth"


@pytest.mark.asyncio
async def test_graph_invalid_max_nodes(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        max_nodes=500,
    )

    assert result["error"] == "invalid_max_nodes"


@pytest.mark.asyncio
async def test_graph_invalid_layer(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        layers=["invalid_layer"],
    )

    assert result["error"] == "invalid_layer"


@pytest.mark.asyncio
async def test_graph_traversal_stats_structure(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        max_depth=2,
        max_nodes=50,
    )

    stats = result["traversal_stats"]
    assert "depth_reached" in stats
    assert "nodes_visited" in stats
    assert "edges_traversed" in stats
    assert stats["depth_reached"] == 2
    assert stats["nodes_visited"] == 1


@pytest.mark.asyncio
async def test_graph_with_relationship_types_and_layers(mock_deps):
    from context_service.mcp.tools.context_graph import _context_graph

    result = await _context_graph(
        silo_id=str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org")),
        query="test",
        relationship_types=["REFERENCES", "SUPPORTS"],
        layers=["memory", "knowledge"],
    )

    assert "error" not in result
    call_kwargs = mock_deps["svc"].graph_traversal.call_args.kwargs
    assert call_kwargs["relationship_types"] == ["REFERENCES", "SUPPORTS"]
    assert call_kwargs["layers"] == ["memory", "knowledge"]
