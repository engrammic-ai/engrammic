"""Tests for context_recall tool."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.mcp.tools.context_recall import _context_recall as _context_recall_import
from tests.fakes.fake_graph_store import FakeGraphStore

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


def _make_node_record(
    node_id: str | None = None,
    content: str = "test content",
    layer: str = "memory",
    summary: str | None = None,
    confidence: float | None = 0.9,
    created_at: datetime | None = None,
) -> dict:
    """Build a node dict matching the shape returned by _context_get."""
    return {
        "node_id": node_id or str(uuid.uuid4()),
        "content": content,
        "type": "Document",
        "layer": layer,
        "summary": summary,
        "confidence": confidence,
        "created_at": (created_at or datetime(2026, 1, 1, tzinfo=UTC)).isoformat(),
        "tags": None,
        "silo_id": _SILO_ID,
        "properties": {},
        "source_uri": None,
        "content_hash": None,
    }


def _make_fake_ctx_service(
    node: object | None = None,
    graph_store: FakeGraphStore | None = None,
) -> MagicMock:
    """Return a minimal context-service mock backed by an optional FakeGraphStore."""
    svc = MagicMock()
    svc.graph_store = graph_store or FakeGraphStore()

    async def _get(node_id: object, silo_id: object) -> object:
        return node

    svc.get = _get
    return svc


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
    assert kwargs.get("layers") == ["memory"] or mock_query.call_args.kwargs.get("layers") == [
        "memory"
    ]


@pytest.mark.asyncio
async def test_recall_passes_top_k_to_query(mock_query):
    from context_service.mcp.tools.context_recall import _context_recall

    await _context_recall(silo_id=_SILO_ID, query="test", top_k=5, depth=0)

    mock_query.assert_called_once()
    call_kwargs = mock_query.call_args.kwargs
    assert call_kwargs.get("top_k") == 5


# ---------------------------------------------------------------------------
# FakeGraphStore integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_seeded_node_data():
    """_context_get returns the node seeded via ctx_svc.get; data passes through _context_recall."""
    from context_service.services.models import Node

    node_id = uuid.uuid4()
    silo_uuid = uuid.UUID(_SILO_ID)
    created = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)

    node = Node(
        id=node_id,
        type="Document",
        content="the seeded content",
        properties={"layer": "knowledge", "confidence": 0.85},
        silo_id=silo_uuid,
        created_at=created,
    )

    fake_store = FakeGraphStore()
    fake_svc = _make_fake_ctx_service(node=node, graph_store=fake_store)

    auth = MagicMock()
    auth.org_id = "test-org"

    with (
        patch(
            "context_service.mcp.tools.context_get.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_get.get_context_service",
            return_value=fake_svc,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        result = await _context_recall_import(silo_id=_SILO_ID, node_ids=[str(node_id)], depth=0)

    assert "nodes" in result
    nodes = result["nodes"]
    assert len(nodes) == 1
    assert nodes[0]["node_id"] == str(node_id)
    assert nodes[0]["content"] == "the seeded content"
    assert nodes[0]["layer"] == "knowledge"
    assert nodes[0]["confidence"] == 0.85


@pytest.mark.asyncio
async def test_include_content_false_projects_node_fields():
    """include_content=False strips content and returns only the 5-field projection."""
    from context_service.services.models import Node

    node_id = uuid.uuid4()
    silo_uuid = uuid.UUID(_SILO_ID)
    created = datetime(2026, 4, 1, tzinfo=UTC)

    node = Node(
        id=node_id,
        type="Document",
        content="sensitive full content that should not appear",
        properties={"layer": "memory", "summary": "brief summary", "confidence": 0.7},
        silo_id=silo_uuid,
        created_at=created,
    )

    fake_store = FakeGraphStore()
    fake_svc = _make_fake_ctx_service(node=node, graph_store=fake_store)

    auth = MagicMock()
    auth.org_id = "test-org"

    with (
        patch(
            "context_service.mcp.tools.context_get.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_get.get_context_service",
            return_value=fake_svc,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        result = await _context_recall_import(
            silo_id=_SILO_ID,
            node_ids=[str(node_id)],
            depth=0,
            include_content=False,
        )

    assert "nodes" in result
    projected = result["nodes"][0]
    assert set(projected.keys()) == {"node_id", "layer", "summary", "created_at", "confidence"}
    assert "content" not in projected
    assert projected["summary"] == "brief summary"
    assert projected["confidence"] == 0.7
    assert projected["layer"] == "memory"


@pytest.mark.asyncio
async def test_include_content_false_falls_back_to_content_truncation():
    """When no summary, include_content=False uses first 200 chars of content as summary."""
    from context_service.services.models import Node

    node_id = uuid.uuid4()
    silo_uuid = uuid.UUID(_SILO_ID)
    long_content = "x" * 500

    node = Node(
        id=node_id,
        type="Document",
        content=long_content,
        properties={"layer": "memory"},
        silo_id=silo_uuid,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )

    fake_store = FakeGraphStore()
    fake_svc = _make_fake_ctx_service(node=node, graph_store=fake_store)

    auth = MagicMock()
    auth.org_id = "test-org"

    with (
        patch(
            "context_service.mcp.tools.context_get.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_get.get_context_service",
            return_value=fake_svc,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        result = await _context_recall_import(
            silo_id=_SILO_ID,
            node_ids=[str(node_id)],
            depth=0,
            include_content=False,
        )

    projected = result["nodes"][0]
    assert projected["summary"] == "x" * 200
    assert "content" not in projected


@pytest.mark.asyncio
async def test_reflections_query_uses_fake_graph_store():
    """include_reflections=True triggers execute_query on graph_store; FakeGraphStore captures it."""
    from context_service.services.models import Node

    node_id = uuid.uuid4()
    silo_uuid = uuid.UUID(_SILO_ID)

    node = Node(
        id=node_id,
        type="Document",
        content="node with reflections",
        properties={"layer": "knowledge"},
        silo_id=silo_uuid,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )

    fake_store = FakeGraphStore()
    reflection_row = {
        "observation": "agent noted this is useful",
        "agent_id": "agent:test",
        "created_at": "2026-04-01T00:00:00+00:00",
    }
    fake_store.seed_query_result([reflection_row])

    fake_svc = _make_fake_ctx_service(node=node, graph_store=fake_store)

    auth = MagicMock()
    auth.org_id = "test-org"

    with (
        patch(
            "context_service.mcp.tools.context_get.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_get.get_context_service",
            return_value=fake_svc,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        result = await _context_recall_import(
            silo_id=_SILO_ID,
            node_ids=[str(node_id)],
            depth=0,
            include_reflections=True,
        )

    assert len(fake_store.query_log) == 1
    queried_cypher, queried_params = fake_store.query_log[0]
    assert queried_params["node_id"] == str(node_id)
    assert queried_params["silo_id"] == _SILO_ID

    nodes = result["nodes"]
    assert nodes[0]["reflections"] == [dict(reflection_row)]


@pytest.mark.asyncio
async def test_reflections_empty_when_no_rows_seeded():
    """When FakeGraphStore returns no rows, reflections list is empty."""
    from context_service.services.models import Node

    node_id = uuid.uuid4()
    silo_uuid = uuid.UUID(_SILO_ID)

    node = Node(
        id=node_id,
        type="Document",
        content="no reflections node",
        properties={"layer": "memory"},
        silo_id=silo_uuid,
        created_at=datetime(2026, 4, 1, tzinfo=UTC),
    )

    fake_store = FakeGraphStore()
    fake_store.seed_query_result([])

    fake_svc = _make_fake_ctx_service(node=node, graph_store=fake_store)
    auth = MagicMock()
    auth.org_id = "test-org"

    with (
        patch(
            "context_service.mcp.tools.context_get.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_get.get_context_service",
            return_value=fake_svc,
        ),
        patch(
            "context_service.mcp.tools.context_get.get_silo_service",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.mcp.tools.context_get.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch("context_service.mcp.tools.context_get.get_redis", return_value=None),
    ):
        result = await _context_recall_import(
            silo_id=_SILO_ID,
            node_ids=[str(node_id)],
            depth=0,
            include_reflections=True,
        )

    assert result["nodes"][0]["reflections"] == []


# ---------------------------------------------------------------------------
# Unit tests for _project_node_without_content
# ---------------------------------------------------------------------------


def test_project_node_without_content_uses_summary():
    from context_service.mcp.tools.context_recall import _project_node_without_content

    node = _make_node_record(summary="precomputed summary", content="full long content")
    projected = _project_node_without_content(node)

    assert set(projected.keys()) == {"node_id", "layer", "summary", "created_at", "confidence"}
    assert projected["summary"] == "precomputed summary"


def test_project_node_without_content_falls_back_to_content():
    from context_service.mcp.tools.context_recall import _project_node_without_content

    node = _make_node_record(summary=None, content="a" * 300)
    projected = _project_node_without_content(node)

    assert projected["summary"] == "a" * 200


def test_project_node_without_content_passes_through_error_entries():
    from context_service.mcp.tools.context_recall import _project_node_without_content

    error_entry = {"error": "node_not_found", "node_id": str(uuid.uuid4()), "message": "gone"}
    assert _project_node_without_content(error_entry) is error_entry


def test_project_node_without_content_missing_node_id_passthrough():
    from context_service.mcp.tools.context_recall import _project_node_without_content

    sentinel = {"error": "invalid_node_id", "node_id": "bad-uuid"}
    assert _project_node_without_content(sentinel) is sentinel
