"""Tests for conflict status and credibility surfacing in recall."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from context_service.mcp.tools import recall as recall_mod


class _FakePreset:
    param_overrides: dict[str, int] = {}


class _FakeResolver:
    async def resolve(self, silo_id: str) -> _FakePreset:
        return _FakePreset()


def _make_auth(org_id: str = "org-test", session_id: str = "session-test"):
    class _Auth:
        pass

    auth = _Auth()
    auth.org_id = org_id  # type: ignore[attr-defined]
    auth.session_id = session_id  # type: ignore[attr-defined]
    return auth


def _patch_base(monkeypatch: pytest.MonkeyPatch, result: dict) -> None:
    """Patch out external dependencies so _recall_impl can run in unit tests."""
    auth = _make_auth()

    async def _fake_context_recall(**_kwargs: object) -> dict:  # type: ignore[type-arg]
        return result

    async def _auth() -> object:
        return auth

    monkeypatch.setattr(recall_mod, "_context_recall", _fake_context_recall)
    monkeypatch.setattr(recall_mod, "get_mcp_auth_context", _auth)
    monkeypatch.setattr(recall_mod, "derive_silo_id", lambda _: "silo-1")
    monkeypatch.setattr(recall_mod, "get_preset_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(recall_mod, "track_tool_usage", AsyncMock())
    monkeypatch.setattr(recall_mod, "get_redis", lambda: None)
    monkeypatch.setattr(recall_mod, "record_recall_latency", lambda *_a, **_kw: None)
    monkeypatch.setattr(recall_mod, "record_recall_depth", lambda *_a, **_kw: None)
    monkeypatch.setattr(recall_mod, "record_recall_result_count", lambda *_a, **_kw: None)
    monkeypatch.setattr(recall_mod, "record_mcp_tool", lambda *_a, **_kw: None)


@pytest.mark.asyncio
async def test_conflict_status_promoted_for_query_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Query-path results with conflict_status are surfaced at top level."""
    node_id = str(uuid4())
    _patch_base(
        monkeypatch,
        {
            "results": [
                {
                    "node_id": node_id,
                    "content": "conflicting fact",
                    "layer": "knowledge",
                    "conflict_status": "unresolved",
                    "credibility": 0.7,
                    "credibility_factors": {"source_tier": "validated"},
                }
            ]
        },
    )

    result = await recall_mod._recall_impl(query="test query")

    items = result["results"]
    assert len(items) == 1
    assert items[0]["conflict_status"] == "unresolved"
    assert items[0]["credibility"] == pytest.approx(0.7)
    assert items[0]["credibility_factors"] == {"source_tier": "validated"}


@pytest.mark.asyncio
async def test_conflict_status_promoted_from_properties_for_get_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Get-path results with conflict fields in `properties` are promoted to top level."""
    node_id = str(uuid4())
    _patch_base(
        monkeypatch,
        {
            "results": [
                {
                    "node_id": node_id,
                    "content": "a fact",
                    "layer": "knowledge",
                    # No top-level conflict fields; they live in properties (get path)
                    "properties": {
                        "conflict_status": "unresolved",
                        "credibility": 0.85,
                        "credibility_factors": {"source_tier": "authoritative"},
                    },
                }
            ]
        },
    )

    result = await recall_mod._recall_impl(node_ids=[node_id])

    items = result["results"]
    assert len(items) == 1
    assert items[0]["conflict_status"] == "unresolved"
    assert items[0]["credibility"] == pytest.approx(0.85)
    assert items[0]["credibility_factors"] == {"source_tier": "authoritative"}


@pytest.mark.asyncio
async def test_has_unresolved_conflicts_true_when_any_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """has_unresolved_conflicts is True when at least one item has conflict_status='unresolved'."""
    _patch_base(
        monkeypatch,
        {
            "results": [
                {
                    "node_id": str(uuid4()),
                    "content": "resolved fact",
                    "conflict_status": "resolved_supersede",
                    "credibility": 0.6,
                },
                {
                    "node_id": str(uuid4()),
                    "content": "conflicting fact",
                    "conflict_status": "unresolved",
                    "credibility": 0.5,
                },
            ]
        },
    )

    result = await recall_mod._recall_impl(query="test query")

    assert result["has_unresolved_conflicts"] is True


@pytest.mark.asyncio
async def test_has_unresolved_conflicts_false_when_all_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """has_unresolved_conflicts is False when no item has conflict_status='unresolved'."""
    _patch_base(
        monkeypatch,
        {
            "results": [
                {
                    "node_id": str(uuid4()),
                    "content": "clean fact",
                    "conflict_status": "none",
                    "credibility": 0.9,
                },
            ]
        },
    )

    result = await recall_mod._recall_impl(query="test query")

    assert result["has_unresolved_conflicts"] is False


@pytest.mark.asyncio
async def test_has_unresolved_conflicts_false_when_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """has_unresolved_conflicts is False when results list is empty."""
    _patch_base(monkeypatch, {"results": []})

    result = await recall_mod._recall_impl(query="empty query")

    assert result["has_unresolved_conflicts"] is False


@pytest.mark.asyncio
async def test_conflict_status_defaults_to_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Items with no conflict fields default to conflict_status='none' and credibility=0.0."""
    node_id = str(uuid4())
    _patch_base(
        monkeypatch,
        {
            "results": [
                {
                    "node_id": node_id,
                    "content": "old node with no conflict fields",
                    "layer": "memory",
                }
            ]
        },
    )

    result = await recall_mod._recall_impl(query="test")

    items = result["results"]
    assert items[0]["conflict_status"] == "none"
    assert items[0]["credibility"] == pytest.approx(0.0)
    assert items[0]["credibility_factors"] is None


@pytest.mark.asyncio
async def test_nodes_path_also_gets_conflict_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Graph traversal returns 'nodes' key; conflict fields are surfaced there too."""
    node_id = str(uuid4())
    _patch_base(
        monkeypatch,
        {
            "nodes": [
                {
                    "node_id": node_id,
                    "content": "traversal node",
                    "conflict_status": "unresolved",
                    "credibility": 0.55,
                }
            ]
        },
    )

    result = await recall_mod._recall_impl(query="q", depth=1)

    items = result["nodes"]
    assert items[0]["conflict_status"] == "unresolved"
    assert result["has_unresolved_conflicts"] is True


@pytest.mark.asyncio
async def test_error_items_not_processed_for_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Items containing an 'error' key are skipped during conflict field promotion."""
    _patch_base(
        monkeypatch,
        {
            "results": [
                {"error": "node_not_found", "node_id": str(uuid4())},
                {
                    "node_id": str(uuid4()),
                    "content": "valid",
                    "conflict_status": "none",
                    "credibility": 0.8,
                },
            ]
        },
    )

    result = await recall_mod._recall_impl(query="test")

    # Only the valid item is processed; error item is untouched
    assert result["has_unresolved_conflicts"] is False
    # error item should not have conflict_status injected
    error_item = result["results"][0]
    assert "error" in error_item
    assert "conflict_status" not in error_item


@pytest.mark.asyncio
async def test_query_result_carries_conflict_fields() -> None:
    """QueryResult dataclass has conflict_status, credibility, credibility_factors fields."""
    from context_service.services.models import QueryResult

    r = QueryResult(
        node_id=uuid4(),
        layer="knowledge",
        content="test",
        confidence=0.9,
        relevance_score=0.8,
        conflict_status="unresolved",
        credibility=0.72,
        credibility_factors={"source_tier": "validated", "method": "direct"},
    )
    assert r.conflict_status == "unresolved"
    assert r.credibility == pytest.approx(0.72)
    assert r.credibility_factors is not None
    assert r.credibility_factors["source_tier"] == "validated"


def test_query_result_default_conflict_fields() -> None:
    """QueryResult defaults to conflict_status='none' and credibility=0.0."""
    from context_service.services.models import QueryResult

    r = QueryResult(
        node_id=uuid4(),
        layer="memory",
        content="test",
        confidence=1.0,
        relevance_score=0.5,
    )
    assert r.conflict_status == "none"
    assert r.credibility == pytest.approx(0.0)
    assert r.credibility_factors is None
