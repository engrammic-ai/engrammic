"""Tests: emit_edge_access_event is called for each edge traversed during graph recall."""

from __future__ import annotations

import uuid
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_NODE_A = str(uuid.uuid4())
_NODE_B = str(uuid.uuid4())
_NODE_C = str(uuid.uuid4())


def _graph_result(edges: list[dict]) -> dict:
    return {
        "nodes": [{"node_id": _NODE_A}, {"node_id": _NODE_B}],
        "edges": edges,
        "traversal_stats": {"depth_reached": 1, "nodes_visited": 2, "edges_traversed": len(edges)},
        "metadata": {},
    }


@pytest.fixture
def mock_graph_deps():
    """Patch all external dependencies for _context_graph."""
    redis = AsyncMock()
    with (
        patch(
            "context_service.mcp.tools.context_graph.get_mcp_auth_context",
            new_callable=AsyncMock,
        ) as auth_mock,
        patch("context_service.mcp.tools.context_graph.get_context_service") as svc_mock,
        patch(
            "context_service.mcp.tools.context_graph.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_graph.validate_silo_ownership",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("context_service.mcp.tools.context_graph.get_redis", return_value=redis),
        patch(
            "context_service.mcp.tools.context_graph.emit_edge_access_event",
            new_callable=AsyncMock,
        ) as emit_mock,
    ):
        auth = MagicMock()
        auth.org_id = "test-org"
        auth_mock.return_value = auth

        svc = AsyncMock()
        svc_mock.return_value = svc

        # Silo service returns a silo without causal metadata by default
        silo_svc = MagicMock()
        silo_svc.get_by_id = AsyncMock(return_value=None)

        yield {"svc": svc, "redis": redis, "emit": emit_mock}


@pytest.mark.asyncio
async def test_emit_called_for_each_edge(mock_graph_deps):
    """emit_edge_access_event fires once per edge when traversal returns edges."""
    from context_service.mcp.tools.context_graph import _context_graph

    edges = [
        {
            "from_node": _NODE_A,
            "to_node": _NODE_B,
            "relationship": "RELATED_TO",
            "weight": 1.0,
            "inferred": False,
        },
        {
            "from_node": _NODE_B,
            "to_node": _NODE_C,
            "relationship": "SUPPORTS",
            "weight": 0.8,
            "inferred": False,
        },
    ]
    mock_graph_deps["svc"].graph_traversal = AsyncMock(return_value=_make_graph_result(edges))

    await _context_graph(silo_id=_SILO_ID, seed_nodes=[_NODE_A], max_depth=1)

    emit = mock_graph_deps["emit"]
    assert emit.await_count == 2


@pytest.mark.asyncio
async def test_emit_not_called_when_no_edges(mock_graph_deps):
    """emit_edge_access_event is not called when traversal returns no edges."""
    from context_service.mcp.tools.context_graph import _context_graph

    mock_graph_deps["svc"].graph_traversal = AsyncMock(return_value=_make_graph_result([]))

    await _context_graph(silo_id=_SILO_ID, seed_nodes=[_NODE_A], max_depth=1)

    mock_graph_deps["emit"].assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_called_with_correct_args(mock_graph_deps):
    """emit_edge_access_event receives from_node, to_node, edge_type and traversal_context."""
    from context_service.mcp.tools.context_graph import _context_graph

    edges = [
        {
            "from_node": _NODE_A,
            "to_node": _NODE_B,
            "relationship": "CAUSES",
            "weight": 1.0,
            "inferred": False,
        },
    ]
    mock_graph_deps["svc"].graph_traversal = AsyncMock(return_value=_make_graph_result(edges))

    await _context_graph(silo_id=_SILO_ID, seed_nodes=[_NODE_A], max_depth=1)

    mock_graph_deps["emit"].assert_awaited_once_with(
        redis=mock_graph_deps["redis"],
        silo_id=ANY,
        from_node=_NODE_A,
        to_node=_NODE_B,
        edge_type="CAUSES",
        traversal_context="recall",
    )


@pytest.mark.asyncio
async def test_emit_redis_none_does_not_raise(mock_graph_deps):
    """When Redis is unavailable (None), graph traversal still returns results."""
    from context_service.mcp.tools.context_graph import _context_graph

    edges = [
        {
            "from_node": _NODE_A,
            "to_node": _NODE_B,
            "relationship": "RELATED_TO",
            "weight": 1.0,
            "inferred": False,
        },
    ]
    mock_graph_deps["svc"].graph_traversal = AsyncMock(return_value=_make_graph_result(edges))
    # Simulate Redis being absent
    with patch("context_service.mcp.tools.context_graph.get_redis", return_value=None):
        result = await _context_graph(silo_id=_SILO_ID, seed_nodes=[_NODE_A], max_depth=1)

    assert "edges" in result


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

from context_service.services.context import GraphResult  # noqa: E402


def _make_graph_result(edges: list[dict]) -> GraphResult:
    nodes = [
        {
            "node_id": _NODE_A,
            "type": "context",
            "content": "a",
            "layer": "memory",
            "confidence": None,
        },
        {
            "node_id": _NODE_B,
            "type": "context",
            "content": "b",
            "layer": "memory",
            "confidence": None,
        },
        {
            "node_id": _NODE_C,
            "type": "context",
            "content": "c",
            "layer": "memory",
            "confidence": None,
        },
    ]
    edge_dicts = [
        {
            "from_node": e["from_node"],
            "to_node": e["to_node"],
            "relationship": e["relationship"],
            "weight": e.get("weight", 1.0),
            "inferred": e.get("inferred", False),
        }
        for e in edges
    ]
    return GraphResult(
        nodes=nodes,
        edges=edge_dicts,
        depth_reached=1,
        nodes_visited=len(nodes),
        edges_traversed=len(edges),
    )
