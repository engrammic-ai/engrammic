"""Tests for recall include_inactive parameter and status filtering."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))


def _make_node(node_id: str | None = None, state: str | None = "ACTIVE") -> dict:
    """Build a node dict as returned by _context_get."""
    nid = node_id or str(uuid.uuid4())
    props: dict = {"layer": "memory", "confidence": 0.8}
    if state is not None:
        props["state"] = state
    return {
        "node_id": nid,
        "content": "test content",
        "type": "Document",
        "layer": "memory",
        "properties": props,
        "confidence": 0.8,
    }


def _make_get_result(nodes: list[dict]) -> dict:
    return {"nodes": nodes}


def _make_query_result(results: list[dict] | None = None) -> dict:
    return {
        "results": results or [],
        "total_candidates": len(results or []),
        "search_time_ms": 5,
        "search_mode": "hybrid",
        "reflection_suggested": False,
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# _filter_inactive_nodes unit tests
# ---------------------------------------------------------------------------


def test_filter_inactive_removes_superseded():
    from context_service.mcp.tools.context_recall import _filter_inactive_nodes

    active = _make_node(state="ACTIVE")
    superseded = _make_node(state="SUPERSEDED")
    tombstoned = _make_node(state="TOMBSTONED")

    result = _filter_inactive_nodes([active, superseded, tombstoned])

    assert len(result) == 1
    assert result[0]["node_id"] == active["node_id"]


def test_filter_inactive_keeps_nodes_without_state():
    from context_service.mcp.tools.context_recall import _filter_inactive_nodes

    no_state = _make_node(state=None)
    result = _filter_inactive_nodes([no_state])
    assert len(result) == 1


def test_filter_inactive_passes_through_error_sentinels():
    from context_service.mcp.tools.context_recall import _filter_inactive_nodes

    error_node = {"error": "node_not_found", "node_id": str(uuid.uuid4())}
    result = _filter_inactive_nodes([error_node])
    assert len(result) == 1
    assert "error" in result[0]


def test_filter_inactive_keeps_active():
    from context_service.mcp.tools.context_recall import _filter_inactive_nodes

    active = _make_node(state="ACTIVE")
    result = _filter_inactive_nodes([active])
    assert len(result) == 1


# ---------------------------------------------------------------------------
# _context_recall: include_inactive=False (default) excludes inactive nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_default_excludes_superseded_nodes():
    """By default (include_inactive=False), superseded nodes are filtered out."""
    from context_service.mcp.tools.context_recall import _context_recall

    active = _make_node(state="ACTIVE")
    superseded = _make_node(state="SUPERSEDED")
    get_result = _make_get_result([active, superseded])

    node_id = str(uuid.uuid4())
    with patch(
        "context_service.mcp.tools.context_recall._context_get",
        new=AsyncMock(return_value=get_result),
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            node_ids=[node_id],
            depth=0,
            include_inactive=False,
        )

    assert "nodes" in result
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["node_id"] == active["node_id"]


@pytest.mark.asyncio
async def test_recall_include_inactive_true_returns_all_nodes():
    """When include_inactive=True, superseded nodes are included."""
    from context_service.mcp.tools.context_recall import _context_recall

    active = _make_node(state="ACTIVE")
    superseded = _make_node(state="SUPERSEDED")
    get_result = _make_get_result([active, superseded])

    node_id = str(uuid.uuid4())
    with patch(
        "context_service.mcp.tools.context_recall._context_get",
        new=AsyncMock(return_value=get_result),
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            node_ids=[node_id],
            depth=0,
            include_inactive=True,
        )

    assert "nodes" in result
    assert len(result["nodes"]) == 2


@pytest.mark.asyncio
async def test_recall_query_path_passes_include_superseded():
    """include_inactive=True is forwarded as include_superseded to _context_query."""
    from context_service.mcp.tools.context_recall import _context_recall

    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new=AsyncMock(return_value=_make_query_result()),
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="some query",
            depth=0,
            include_inactive=True,
        )

    mock_query.assert_called_once()
    kwargs = mock_query.call_args.kwargs
    assert kwargs.get("include_superseded") is True


@pytest.mark.asyncio
async def test_recall_query_path_default_excludes_superseded():
    """Default recall (include_inactive=False) passes include_superseded=False."""
    from context_service.mcp.tools.context_recall import _context_recall

    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new=AsyncMock(return_value=_make_query_result()),
    ) as mock_query:
        await _context_recall(
            silo_id=_SILO_ID,
            query="some query",
            depth=0,
        )

    mock_query.assert_called_once()
    kwargs = mock_query.call_args.kwargs
    assert kwargs.get("include_superseded") is False


# ---------------------------------------------------------------------------
# Migration query correctness (unit tests against query strings)
# ---------------------------------------------------------------------------


def test_backfill_superseded_state_targets_active_nodes():
    from context_service.db.queries import BACKFILL_SUPERSEDED_STATE

    assert "SUPERSEDES" in BACKFILL_SUPERSEDED_STATE
    assert "SUPERSEDED" in BACKFILL_SUPERSEDED_STATE
    assert "ACTIVE" in BACKFILL_SUPERSEDED_STATE


def test_backfill_active_state_targets_null_state():
    from context_service.db.queries import BACKFILL_ACTIVE_STATE

    assert "ACTIVE" in BACKFILL_ACTIVE_STATE
    assert "IS NULL" in BACKFILL_ACTIVE_STATE

