"""E2E recall quality tests for ContextService.query.

Uses controlled vectors and mock infrastructure to verify that:
- semantically relevant documents rank above unrelated ones
- rare-term exact matches surface the correct document
- freshness multiplier causes newer documents to outrank stale ones

No live docker stack required — mocks replace Qdrant and Memgraph batch
fetches while exercising the full query() scoring and ranking pipeline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from context_service.services.context import ContextService
from context_service.services.models import Node, QueryResult, ScopeContext

NOW = datetime(2026, 5, 1, tzinfo=UTC)

_SILO_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_SCOPE = ScopeContext(org_id="org-recall-test", silo_id=_SILO_ID)


def _node(node_id: str, content: str, created_at: datetime | None = None) -> Node:
    return Node(
        id=uuid.UUID(node_id),
        type="Document",
        content=content,
        silo_id=_SILO_ID,
        properties={"layer": "memory", "confidence": 1.0},
        source_uri=None,
        content_hash=None,
        created_at=created_at or NOW,
    )


def _result(node_id: str, score: float) -> SimpleNamespace:
    return SimpleNamespace(node_id=node_id, score=score)


def _make_service(
    qdrant_results: list[SimpleNamespace],
    node_map: dict[str, Node],
) -> tuple[ContextService, AsyncMock]:
    embedding = AsyncMock()
    embedding.embed_query = AsyncMock(return_value=[0.0] * 8)

    qdrant = AsyncMock()
    qdrant.search = AsyncMock(return_value=qdrant_results)

    svc = ContextService(memgraph=AsyncMock(), qdrant=qdrant, embedding=embedding)

    async def fake_batch_fetch(ids: list[str], silo_id: uuid.UUID) -> dict[str, Node]:
        return {k: v for k, v in node_map.items() if k in ids}

    svc._batch_fetch_nodes = fake_batch_fetch  # type: ignore[method-assign]
    return svc, embedding


_ML_IDS = [
    "11111111-0000-0000-0000-000000000001",
    "11111111-0000-0000-0000-000000000002",
    "11111111-0000-0000-0000-000000000003",
]
_COOKING_IDS = [
    "22222222-0000-0000-0000-000000000001",
    "22222222-0000-0000-0000-000000000002",
]

_ML_CORPUS = [
    _node(_ML_IDS[0], "Neural networks use gradient descent to optimise model weights."),
    _node(_ML_IDS[1], "Transformer architectures rely on self-attention for sequence modelling."),
    _node(_ML_IDS[2], "Supervised machine learning maps labelled inputs to predicted outputs."),
]
_COOKING_CORPUS = [
    _node(_COOKING_IDS[0], "Sauteing onions in butter releases natural sugars and adds depth."),
    _node(_COOKING_IDS[1], "A good risotto requires constant stirring to develop the starch."),
]

_RARE_DOC_ID = "33333333-0000-0000-0000-000000000001"
_RARE_OTHER_IDS = [
    "44444444-0000-0000-0000-000000000001",
    "44444444-0000-0000-0000-000000000002",
]
_RARE_DOC = _node(
    _RARE_DOC_ID,
    "NovusEdge implements the EAG paradigm with a CITE schema for epistemic layering.",
)
_RARE_OTHER = [
    _node(_RARE_OTHER_IDS[0], "Graph databases store relationships as first-class citizens."),
    _node(
        _RARE_OTHER_IDS[1], "Embeddings encode semantic meaning as dense floating-point vectors."
    ),
]


@pytest.mark.integration
class TestRecallQuality:
    async def test_relevant_docs_rank_higher(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ML documents must occupy the top-3 results for a machine learning query."""
        # ML docs score higher from the mock Qdrant; cooking docs score lower.
        qdrant_results = [
            _result(_ML_IDS[0], 0.92),
            _result(_ML_IDS[1], 0.89),
            _result(_ML_IDS[2], 0.85),
            _result(_COOKING_IDS[0], 0.41),
            _result(_COOKING_IDS[1], 0.38),
        ]
        node_map: dict[str, Node] = {str(n.id): n for n in _ML_CORPUS + _COOKING_CORPUS}

        svc, _ = _make_service(qdrant_results, node_map)
        monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

        results: list[QueryResult] = await svc.query(_SCOPE, "machine learning neural networks")

        assert len(results) >= 3
        top3_ids = {str(r.node_id) for r in results[:3]}
        ml_id_set = set(_ML_IDS)
        overlap = top3_ids & ml_id_set
        assert len(overlap) == 3, (
            f"Expected all 3 ML docs in top-3, got {top3_ids} vs ML set {ml_id_set}"
        )

        # All cooking docs should rank below all ML docs.
        ml_positions = [i for i, r in enumerate(results) if str(r.node_id) in ml_id_set]
        cooking_positions = [
            i for i, r in enumerate(results) if str(r.node_id) in set(_COOKING_IDS)
        ]
        assert max(ml_positions) < min(cooking_positions), (
            "At least one cooking doc ranked above an ML doc"
        )

    async def test_rare_term_exact_match(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A proper-noun query for 'NovusEdge EAG CITE' must return the exact-match doc first."""
        qdrant_results = [
            _result(_RARE_DOC_ID, 0.95),
            _result(_RARE_OTHER_IDS[0], 0.52),
            _result(_RARE_OTHER_IDS[1], 0.48),
        ]
        node_map: dict[str, Node] = {str(n.id): n for n in [_RARE_DOC] + _RARE_OTHER}

        svc, _ = _make_service(qdrant_results, node_map)
        monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

        results = await svc.query(_SCOPE, "NovusEdge EAG CITE schema")

        assert results, "Expected at least one result"
        assert str(results[0].node_id) == _RARE_DOC_ID, (
            f"Exact-match doc not ranked first; got {results[0].node_id}"
        )

    async def test_freshness_affects_ranking(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A recent document must outrank a stale document when base scores are equal."""
        fresh_id = "55555555-0000-0000-0000-000000000001"
        stale_id = "55555555-0000-0000-0000-000000000002"

        content = "Context retrieval systems store and surface relevant knowledge."
        fresh_node = _node(fresh_id, content, created_at=NOW - timedelta(days=3))
        stale_node = _node(stale_id, content, created_at=NOW - timedelta(days=200))

        # Qdrant returns stale doc first — freshness must invert this.
        qdrant_results = [
            _result(stale_id, 0.9),
            _result(fresh_id, 0.9),
        ]
        node_map = {stale_id: stale_node, fresh_id: fresh_node}

        svc, _ = _make_service(qdrant_results, node_map)
        monkeypatch.setattr("context_service.services.context._now_utc", lambda: NOW)

        results = await svc.query(_SCOPE, "context retrieval knowledge")

        assert len(results) == 2
        result_ids = [str(r.node_id) for r in results]
        assert result_ids[0] == fresh_id, f"Fresh doc should rank first; order was {result_ids}"

        fresh_score = next(r.relevance_score for r in results if str(r.node_id) == fresh_id)
        stale_score = next(r.relevance_score for r in results if str(r.node_id) == stale_id)
        assert fresh_score > stale_score, (
            f"Fresh score {fresh_score:.4f} should exceed stale score {stale_score:.4f}"
        )
