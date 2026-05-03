"""Tests for semantic filtering in temporal_query.

Covers:
- query param triggers Qdrant search when embedding is available
- candidate IDs passed to filtered Memgraph query
- fallback to unfiltered TEMPORAL_QUERY when query is empty string
- fallback to unfiltered TEMPORAL_QUERY when no embedding service
- results ordered by valid_from DESC (preserved from Memgraph)
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.services.context import ContextService


def _make_svc(
    *,
    has_embedding: bool = True,
    qdrant_ids: list[str] | None = None,
    memgraph_rows: list[dict] | None = None,
) -> ContextService:
    svc = MagicMock(spec=ContextService)

    if has_embedding:
        svc._embedding = MagicMock()
        svc._embedding.embed_query = AsyncMock(return_value=[0.1, 0.2, 0.3])
    else:
        svc._embedding = None

    qdrant_result = [MagicMock(node_id=nid, score=0.9) for nid in (qdrant_ids or [])]
    svc._qdrant = MagicMock()
    svc._qdrant.search = AsyncMock(return_value=qdrant_result)

    svc._memgraph = MagicMock()
    svc._memgraph.execute_query = AsyncMock(return_value=memgraph_rows or [])

    # Bind the real method under test
    svc.temporal_query = ContextService.temporal_query.__get__(svc, ContextService)

    return svc


AS_OF = datetime(2026, 1, 1, tzinfo=UTC)
SILO = "silo-abc"


@pytest.mark.asyncio
async def test_non_empty_query_calls_qdrant() -> None:
    """Non-empty query must trigger Qdrant search."""
    svc = _make_svc(qdrant_ids=["id-1", "id-2"])
    await svc.temporal_query(silo_id=SILO, as_of=AS_OF, query="test concept")
    svc._embedding.embed_query.assert_awaited_once_with("test concept")
    svc._qdrant.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_candidate_ids_passed_to_memgraph() -> None:
    """Memgraph query must receive the candidate_ids filter when query non-empty."""
    svc = _make_svc(qdrant_ids=["id-1", "id-2"])
    await svc.temporal_query(silo_id=SILO, as_of=AS_OF, query="test concept", top_k=5)
    call_kwargs = svc._memgraph.execute_query.call_args
    params = call_kwargs[0][1]  # second positional arg
    assert "candidate_ids" in params
    assert set(params["candidate_ids"]) == {"id-1", "id-2"}


@pytest.mark.asyncio
async def test_empty_query_skips_qdrant() -> None:
    """Empty query string must bypass Qdrant and use unfiltered query."""
    svc = _make_svc()
    await svc.temporal_query(silo_id=SILO, as_of=AS_OF, query="")
    svc._qdrant.search.assert_not_awaited()
    svc._embedding.embed_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_embedding_service_skips_qdrant() -> None:
    """When embedding service is None, fall back to unfiltered query."""
    svc = _make_svc(has_embedding=False)
    await svc.temporal_query(silo_id=SILO, as_of=AS_OF, query="something")
    svc._qdrant.search.assert_not_awaited()


@pytest.mark.asyncio
async def test_qdrant_candidate_limit_is_3x_top_k() -> None:
    """Qdrant search limit must be 3 * top_k."""
    svc = _make_svc(qdrant_ids=["id-1"])
    await svc.temporal_query(silo_id=SILO, as_of=AS_OF, query="foo", top_k=7)
    call_kwargs = svc._qdrant.search.call_args
    assert call_kwargs.kwargs.get("limit") == 21  # 3 * 7


@pytest.mark.asyncio
async def test_results_contain_expected_keys() -> None:
    """Result dicts must include node_id, content, labels, valid_from."""
    row = {
        "id": "id-1",
        "content": "some content",
        "labels": ["Claim"],
        "confidence": 0.8,
        "valid_from": datetime(2025, 6, 1, tzinfo=UTC),
        "valid_to": None,
        "created_at": None,
    }
    svc = _make_svc(qdrant_ids=["id-1"], memgraph_rows=[row])
    results = await svc.temporal_query(
        silo_id=SILO, as_of=AS_OF, query="some content"
    )
    assert len(results) == 1
    assert results[0]["node_id"] == "id-1"
    assert results[0]["content"] == "some content"
    assert "valid_from" in results[0]
