# context_history Semantic Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** Add semantic filtering to temporal_query so the query param filters results before recency sort

**Architecture:** Query Qdrant for semantically relevant node IDs, then filter Memgraph temporal query to those candidates

**Tech Stack:** Qdrant, Memgraph, async Python

---

## Context

`temporal_query` in `src/context_service/services/context.py` (line ~1103) accepts a `query` param marked `# noqa: ARG002` — it is silently ignored. All results are recency-ordered only.

The fix: when `query` is non-empty and an embedding service is available, pre-filter with Qdrant before hitting Memgraph. When `query` is empty or no embedding service is wired, fall back to current behavior (unfiltered temporal scan).

---

## Files

- `src/context_service/db/queries.py` — add `TEMPORAL_QUERY_FILTERED` (ID allowlist variant)
- `src/context_service/services/context.py` — modify `temporal_query`
- `tests/test_temporal_semantic_filter.py` — new test file (written first)

---

## Steps

### Step 1 — Write failing tests

File: `tests/test_temporal_semantic_filter.py`

Create the test file. All tests should fail at this point because `temporal_query` still ignores `query`.

```python
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
from unittest.mock import AsyncMock, MagicMock, patch

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
```

Run to confirm all fail:

```bash
uv run pytest tests/test_temporal_semantic_filter.py -v
```

---

### Step 2 — Add TEMPORAL_QUERY_FILTERED to db/queries.py

File: `src/context_service/db/queries.py`

Add the new query constant immediately after `TEMPORAL_QUERY` (around line 666). It mirrors `TEMPORAL_QUERY` but adds an `n.id IN $candidate_ids` predicate.

```python
# --- Temporal query with semantic pre-filter ---
# candidate_ids comes from a Qdrant pre-filter (top 3*top_k by vector similarity).
# Results are still ordered by valid_from DESC — Qdrant ranking is discarded here.

TEMPORAL_QUERY_FILTERED = (
    "MATCH (n) "
    "WHERE n.silo_id = $silo_id "
    "  AND n.id IN $candidate_ids "
    "  AND ($type_filter IS NULL OR any(label IN labels(n) WHERE label = $type_filter)) "
    "  AND n.valid_from <= $as_of "
    "  AND (n.valid_to IS NULL OR n.valid_to > $as_of) "
    "  AND n.content IS NOT NULL "
    "  AND NOT exists(n.tombstoned_at) "
    "RETURN n.id AS id, n.content AS content, labels(n) AS labels, "
    "       n.confidence AS confidence, n.valid_from AS valid_from, "
    "       n.valid_to AS valid_to, n.created_at AS created_at "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)
```

Verify ruff is happy:

```bash
just lint
```

---

### Step 3 — Modify temporal_query in context.py

File: `src/context_service/services/context.py`

Replace the `temporal_query` method body. The noqa comment on `query` is removed; the full logic is:

1. If `query` is non-empty and `self._embedding` is set, embed query and search Qdrant.
2. Use `TEMPORAL_QUERY_FILTERED` with `candidate_ids` param.
3. Otherwise use existing `TEMPORAL_QUERY` without candidate filter.

Find this block (around line 1103):

```python
    async def temporal_query(
        self,
        silo_id: str,
        as_of: datetime,
        query: str,  # noqa: ARG002
        top_k: int = 10,
        type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Memgraph-only temporal query: return nodes valid at as_of timestamp.

        Bypasses Qdrant entirely — no vector ranking, no split-brain risk.
        Results are ordered by valid_from DESC (most recently valid first).

        Note: the ``query`` parameter is currently unused. Results are recency-
        ordered, not relevance-ranked. Semantic filtering against ``query`` is
        not yet implemented.
        # TODO(v1.1): implement semantic filtering with context_snapshot
        """
        from context_service.db.queries import TEMPORAL_QUERY

        rows = await self._memgraph.execute_query(
            TEMPORAL_QUERY,
            {
                "silo_id": silo_id,
                "as_of": as_of.isoformat(),
                "type_filter": type_filter,
                "limit": top_k,
            },
        )
```

Replace with:

```python
    async def temporal_query(
        self,
        silo_id: str,
        as_of: datetime,
        query: str,
        top_k: int = 10,
        type_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Memgraph temporal query: return nodes valid at as_of timestamp.

        When ``query`` is non-empty and an embedding service is configured,
        Qdrant is used to pre-filter candidate node IDs (top ``3 * top_k`` by
        vector similarity). Memgraph then filters to those candidates and
        orders by ``valid_from DESC``. Qdrant ranking is discarded; recency
        governs final order.

        When ``query`` is empty or no embedding service is wired, falls back
        to a full temporal scan (original behavior).
        """
        from context_service.db.queries import TEMPORAL_QUERY, TEMPORAL_QUERY_FILTERED

        use_semantic_filter = bool(query) and self._embedding is not None

        if use_semantic_filter:
            query_vector = await self._embedding.embed_query(query)
            qdrant_results = await self._qdrant.search(
                vector=query_vector,
                limit=3 * top_k,
                silo_id=silo_id,
            )
            candidate_ids = [r.node_id for r in qdrant_results]
            cypher = TEMPORAL_QUERY_FILTERED
            params: dict[str, Any] = {
                "silo_id": silo_id,
                "candidate_ids": candidate_ids,
                "as_of": as_of.isoformat(),
                "type_filter": type_filter,
                "limit": top_k,
            }
        else:
            cypher = TEMPORAL_QUERY
            params = {
                "silo_id": silo_id,
                "as_of": as_of.isoformat(),
                "type_filter": type_filter,
                "limit": top_k,
            }

        rows = await self._memgraph.execute_query(cypher, params)
```

Run lint and typecheck:

```bash
just check
```

---

### Step 4 — Run tests, confirm green

```bash
uv run pytest tests/test_temporal_semantic_filter.py -v
```

All six tests should pass. Also run the existing temporal-related tests to confirm nothing regressed:

```bash
uv run pytest tests/test_context_query_time_travel.py tests/test_retention_query_filter.py tests/mcp/test_context_query.py -v
```

---

### Step 5 — Full test suite

```bash
just test
```

Confirm no regressions. If `just check` (lint + mypy) is not yet green, fix before proceeding.

---

## Acceptance criteria

- `temporal_query` with a non-empty `query` calls `embed_query` and `qdrant.search` with `limit = 3 * top_k`.
- Memgraph receives `candidate_ids` in params and uses `TEMPORAL_QUERY_FILTERED`.
- Results are returned ordered by `valid_from DESC` (Memgraph controls sort, not Qdrant).
- Empty `query` or missing embedding service uses `TEMPORAL_QUERY` unchanged.
- `just check` passes (mypy strict + ruff).
- All existing temporal tests still pass.

---

## Non-goals

- No changes to the MCP tool layer (`mcp/tools/`) — the `query` param is already threaded through to `temporal_query` by the caller.
- No hybrid/sparse search path for this feature; dense only (matches `lookup` pattern).
- No caching of the Qdrant pre-filter result.
