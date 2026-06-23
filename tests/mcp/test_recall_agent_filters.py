"""Tests for recall() agent filter parameters (Task 8)."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))

_AGENT_A = "agent-alpha"
_AGENT_B = "agent-beta"


def _make_node(node_id: str | None = None, agent_id: str | None = None) -> dict:
    return {
        "node_id": node_id or str(uuid.uuid4()),
        "content": "test",
        "type": "Document",
        "layer": "memory",
        "properties": {"created_by": agent_id, "layer": "memory"},
        "confidence": 0.9,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def _query_result(nodes: list[dict]) -> dict:
    return {
        "results": nodes,
        "total_candidates": len(nodes),
        "search_time_ms": 5,
        "search_mode": "hybrid",
        "reflection_suggested": False,
        "metadata": {},
    }


def _get_result(nodes: list[dict]) -> dict:
    return {"nodes": nodes}


# --- _apply_agent_filters unit tests ---


def test_apply_agent_filters_no_filters():
    from context_service.mcp.tools.context_recall import _apply_agent_filters

    nodes = [_make_node(agent_id=_AGENT_A), _make_node(agent_id=_AGENT_B)]
    result = _apply_agent_filters(nodes, agent_id=None, exclude_agents=[])
    assert result == nodes


def test_apply_agent_filters_agent_id():
    from context_service.mcp.tools.context_recall import _apply_agent_filters

    node_a = _make_node(agent_id=_AGENT_A)
    node_b = _make_node(agent_id=_AGENT_B)
    result = _apply_agent_filters([node_a, node_b], agent_id=_AGENT_A, exclude_agents=[])
    assert result == [node_a]


def test_apply_agent_filters_exclude_agents():
    from context_service.mcp.tools.context_recall import _apply_agent_filters

    node_a = _make_node(agent_id=_AGENT_A)
    node_b = _make_node(agent_id=_AGENT_B)
    result = _apply_agent_filters([node_a, node_b], agent_id=None, exclude_agents=[_AGENT_B])
    assert result == [node_a]


def test_apply_agent_filters_passes_through_errors():
    from context_service.mcp.tools.context_recall import _apply_agent_filters

    error_entry = {"error": "node_not_found", "node_id": "bad-id"}
    node_a = _make_node(agent_id=_AGENT_A)
    result = _apply_agent_filters([error_entry, node_a], agent_id=_AGENT_B, exclude_agents=[])
    # error entry passes through; node_a is filtered out (wrong agent)
    assert error_entry in result
    assert node_a not in result


def test_apply_agent_filters_agent_id_and_exclude_combined():
    from context_service.mcp.tools.context_recall import _apply_agent_filters

    node_a = _make_node(agent_id=_AGENT_A)
    node_b = _make_node(agent_id=_AGENT_B)
    # agent_id filter wins: only AGENT_A nodes; exclude has no effect if it excludes AGENT_A
    result = _apply_agent_filters([node_a, node_b], agent_id=_AGENT_A, exclude_agents=[_AGENT_A])
    # Excluded by exclude_agents even though agent_id matches
    assert result == []


# --- Integration tests through _context_recall ---


@pytest.mark.asyncio
async def test_context_recall_agent_id_filter_on_query_path():
    from context_service.mcp.tools.context_recall import _context_recall

    nid_a = str(uuid.uuid4())
    nid_b = str(uuid.uuid4())
    node_a = _make_node(node_id=nid_a, agent_id=_AGENT_A)
    node_b = _make_node(node_id=nid_b, agent_id=_AGENT_B)
    query_result = _query_result([node_a, node_b])

    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=query_result,
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            query="test",
            depth=0,
            agent_id=_AGENT_A,
            include_content=True,
        )

    returned = result["results"]
    assert len(returned) == 1
    assert returned[0]["node_id"] == nid_a


@pytest.mark.asyncio
async def test_context_recall_exclude_agents_on_query_path():
    from context_service.mcp.tools.context_recall import _context_recall

    nid_a = str(uuid.uuid4())
    nid_b = str(uuid.uuid4())
    node_a = _make_node(node_id=nid_a, agent_id=_AGENT_A)
    node_b = _make_node(node_id=nid_b, agent_id=_AGENT_B)
    query_result = _query_result([node_a, node_b])

    with patch(
        "context_service.mcp.tools.context_recall._context_query",
        new_callable=AsyncMock,
        return_value=query_result,
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            query="test",
            depth=0,
            exclude_agents=[_AGENT_B],
            include_content=True,
        )

    returned = result["results"]
    assert len(returned) == 1
    assert returned[0]["node_id"] == nid_a


@pytest.mark.asyncio
async def test_context_recall_agent_id_filter_on_get_path():
    from context_service.mcp.tools.context_recall import _context_recall

    nid_a = str(uuid.uuid4())
    nid_b = str(uuid.uuid4())
    node_a = _make_node(node_id=nid_a, agent_id=_AGENT_A)
    node_b = _make_node(node_id=nid_b, agent_id=_AGENT_B)
    get_result = _get_result([node_a, node_b])

    with patch(
        "context_service.mcp.tools.context_recall._context_get",
        new_callable=AsyncMock,
        return_value=get_result,
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            node_ids=[nid_a, nid_b],
            depth=0,
            agent_id=_AGENT_A,
        )

    returned = result["nodes"]
    assert len(returned) == 1
    assert returned[0]["node_id"] == nid_a


@pytest.mark.asyncio
async def test_context_recall_include_conflicts_returns_conflict_nodes():
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid.uuid4())
    conflict_nid = str(uuid.uuid4())
    node = _make_node(node_id=nid, agent_id=_AGENT_A)
    conflict_node = _make_node(node_id=conflict_nid, agent_id=_AGENT_B)
    get_result = _get_result([node])
    conflict_get_result = _get_result([conflict_node])

    fake_graph_store = MagicMock()
    fake_graph_store.get_epistemic_edges_for_nodes = AsyncMock(
        return_value={nid: {"supports": [], "derived_from": [], "contradicts": [conflict_nid]}}
    )
    fake_ctx_svc = MagicMock()
    fake_ctx_svc.graph_store = fake_graph_store

    with (
        patch(
            "context_service.mcp.tools.context_recall._context_get",
            new_callable=AsyncMock,
            side_effect=[get_result, conflict_get_result],
        ),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=fake_ctx_svc,
        ),
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            node_ids=[nid],
            depth=0,
            include_conflicts=True,
        )

    assert "conflict_nodes" in result
    assert len(result["conflict_nodes"]) == 1
    assert result["conflict_nodes"][0]["node_id"] == conflict_nid


@pytest.mark.asyncio
async def test_context_recall_include_conflicts_empty_when_none():
    from context_service.mcp.tools.context_recall import _context_recall

    nid = str(uuid.uuid4())
    node = _make_node(node_id=nid, agent_id=_AGENT_A)
    get_result = _get_result([node])

    fake_graph_store = MagicMock()
    fake_graph_store.get_epistemic_edges_for_nodes = AsyncMock(
        return_value={nid: {"supports": [], "derived_from": [], "contradicts": []}}
    )
    fake_ctx_svc = MagicMock()
    fake_ctx_svc.graph_store = fake_graph_store

    with (
        patch(
            "context_service.mcp.tools.context_recall._context_get",
            new_callable=AsyncMock,
            return_value=get_result,
        ),
        patch(
            "context_service.mcp.server.get_context_service",
            return_value=fake_ctx_svc,
        ),
    ):
        result = await _context_recall(
            silo_id=_SILO_ID,
            node_ids=[nid],
            depth=0,
            include_conflicts=True,
        )

    assert result.get("conflict_nodes") == []
