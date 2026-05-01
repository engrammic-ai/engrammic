"""End-to-end freshness ranking test for ContextService.query.

Uses a stubbed embedding service + an in-memory fake of the qdrant + memgraph
batch fetch path, so the test isolates the freshness multiplier behaviour.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from context_service.services.context import ContextService
from context_service.services.models import Node, ScopeContext

NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _make_node(node_id: str, created_at: datetime, content: str) -> Node:
    return Node(
        id=uuid.UUID(node_id),
        type="Document",
        content=content,
        silo_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        properties={"layer": "memory", "confidence": 1.0},
        source_uri=None,
        content_hash=None,
        created_at=created_at,
    )


@pytest.mark.asyncio
async def test_fresher_candidate_outranks_stale_when_scores_tied(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh_id = "11111111-1111-1111-1111-111111111111"
    stale_id = "22222222-2222-2222-2222-222222222222"
    fresh_node = _make_node(fresh_id, NOW - timedelta(days=1), "fresh")
    stale_node = _make_node(stale_id, NOW - timedelta(days=120), "stale")

    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(
        return_value=[
            SimpleNamespace(node_id=stale_id, score=0.9),
            SimpleNamespace(node_id=fresh_id, score=0.9),
        ]
    )

    svc = ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {fresh_id: fresh_node, stale_id: stale_node}

    monkeypatch.setattr(svc, "_batch_fetch_nodes", fake_batch_fetch)

    # Pin "now" used by query() so the test is deterministic.
    monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

    scope = ScopeContext(
        org_id="org-test",
        silo_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
    )
    results = await svc.query(scope=scope, query="anything")

    assert [str(r.node_id) for r in results] == [fresh_id, stale_id]
    # Fresh node retains a higher relevance_score after the multiplier.
    fresh_score = next(r.relevance_score for r in results if str(r.node_id) == fresh_id)
    stale_score = next(r.relevance_score for r in results if str(r.node_id) == stale_id)
    assert fresh_score > stale_score
