"""End-to-end heat ranking test for ContextService.query.

Uses a stubbed embedding service + an in-memory fake of the qdrant + memgraph
batch fetch path, so the test isolates the heat ranking multiplier behaviour.
"""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from context_service.config.settings import get_settings
from context_service.services.context import ContextService
from context_service.services.models import Node, ScopeContext


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Generator[None, None, None]:
    """Clear lru_cache on get_settings before and after each test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


NOW = datetime(2026, 5, 1, tzinfo=UTC)

SILO_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HOT_ID = "11111111-1111-1111-1111-111111111111"
COLD_ID = "22222222-2222-2222-2222-222222222222"


def _make_node(node_id: str, heat_score: float | None = None) -> Node:
    props: dict[str, object] = {"layer": "memory", "confidence": 1.0}
    if heat_score is not None:
        props["heat_score"] = heat_score
    return Node(
        id=uuid.UUID(node_id),
        type="Document",
        content="content",
        silo_id=SILO_ID,
        properties=props,
        source_uri=None,
        content_hash=None,
        created_at=NOW,
    )


def _make_svc() -> ContextService:
    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            SimpleNamespace(node_id=HOT_ID, score=0.9),
            SimpleNamespace(node_id=COLD_ID, score=0.9),
        ]
    )

    return ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)


@pytest.mark.asyncio
async def test_hot_node_outranks_cold_node_when_heat_ranking_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hot node (heat_score=0.9) outranks cold node (heat_score=0.1) at equal
    semantic score when heat_ranking_enabled=True."""
    monkeypatch.setenv("HEAT_RANKING_ENABLED", "true")
    monkeypatch.setenv("HEAT_WEIGHT", "0.1")

    hot_node = _make_node(HOT_ID, heat_score=0.9)
    cold_node = _make_node(COLD_ID, heat_score=0.1)

    svc = _make_svc()

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {HOT_ID: hot_node, COLD_ID: cold_node}

    monkeypatch.setattr(svc, "_batch_fetch_nodes", fake_batch_fetch)
    monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

    scope = ScopeContext(org_id="org-test", silo_id=SILO_ID)
    results = await svc.query(scope=scope, query="anything")

    ids = [str(r.node_id) for r in results]
    assert ids == [HOT_ID, COLD_ID], f"Expected hot first, got {ids}"

    hot_score = next(r.relevance_score for r in results if str(r.node_id) == HOT_ID)
    cold_score = next(r.relevance_score for r in results if str(r.node_id) == COLD_ID)
    assert hot_score > cold_score


@pytest.mark.asyncio
async def test_ranking_unchanged_when_heat_ranking_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ranking matches original Qdrant order when heat_ranking_enabled=False."""
    monkeypatch.setenv("HEAT_RANKING_ENABLED", "false")
    monkeypatch.setenv("HEAT_WEIGHT", "0.1")
    monkeypatch.setenv("FRESHNESS_WEIGHT", "0.0")

    # Qdrant returns COLD_ID first at higher score; heat should not change this.
    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            SimpleNamespace(node_id=COLD_ID, score=0.95),
            SimpleNamespace(node_id=HOT_ID, score=0.80),
        ]
    )

    svc = ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)

    hot_node = _make_node(HOT_ID, heat_score=0.9)
    cold_node = _make_node(COLD_ID, heat_score=0.1)

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {HOT_ID: hot_node, COLD_ID: cold_node}

    monkeypatch.setattr(svc, "_batch_fetch_nodes", fake_batch_fetch)
    monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

    scope = ScopeContext(org_id="org-test", silo_id=SILO_ID)
    results = await svc.query(scope=scope, query="anything")

    ids = [str(r.node_id) for r in results]
    assert ids == [COLD_ID, HOT_ID], f"Expected original Qdrant order, got {ids}"


@pytest.mark.asyncio
async def test_missing_heat_score_uses_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Node with no heat_score uses 0.5 fallback, placing it between hot and cold."""
    monkeypatch.setenv("HEAT_RANKING_ENABLED", "true")
    monkeypatch.setenv("HEAT_WEIGHT", "0.2")
    monkeypatch.setenv("FRESHNESS_WEIGHT", "0.0")

    neutral_id = "33333333-3333-3333-3333-333333333333"

    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            SimpleNamespace(node_id=HOT_ID, score=1.0),
            SimpleNamespace(node_id=neutral_id, score=1.0),
            SimpleNamespace(node_id=COLD_ID, score=1.0),
        ]
    )

    svc = ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)

    hot_node = _make_node(HOT_ID, heat_score=1.0)
    neutral_node = _make_node(neutral_id, heat_score=None)  # no heat_score
    cold_node = _make_node(COLD_ID, heat_score=0.0)

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {HOT_ID: hot_node, neutral_id: neutral_node, COLD_ID: cold_node}

    monkeypatch.setattr(svc, "_batch_fetch_nodes", fake_batch_fetch)
    monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

    scope = ScopeContext(org_id="org-test", silo_id=SILO_ID)
    results = await svc.query(scope=scope, query="anything")

    score_map = {str(r.node_id): r.relevance_score for r in results}
    assert score_map[HOT_ID] > score_map[neutral_id] > score_map[COLD_ID], (
        f"Expected hot > neutral(fallback) > cold; got {score_map}"
    )
