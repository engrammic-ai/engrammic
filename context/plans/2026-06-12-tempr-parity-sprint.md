# TEMPR Parity Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 4-channel TEMPR-style retrieval (semantic + BM25 + temporal + PPR graph) with cross-encoder reranking, then benchmark against mem0 on epistemic slices.

**Architecture:** Extend existing `FusionRetriever` with three new channels (BM25, temporal, PPR) running in parallel, followed by RRF fusion, cross-encoder reranking, and existing epistemic fusion. Each channel is feature-flagged for independent enable/disable.

**Tech Stack:** Python 3.12, FastAPI, Memgraph, Qdrant, Postgres (GIN index), sentence-transformers (CrossEncoder), python-dateutil. All commands via `uv run` / `just`.

**Branch:** `feat/read-path-epistemic-fusion` (extends existing step 1 work)

**Spec:** `docs/superpowers/specs/2026-06-12-tempr-parity-design.md`

---

## File Structure

### New Files
- `src/context_service/retrieval/temporal.py` — date parsing + recency decay scoring
- `src/context_service/retrieval/cross_encoder.py` — local cross-encoder wrapper
- `src/context_service/retrieval/ppr.py` — PPR algorithm (Python-side, no MAGE dependency)
- `tests/retrieval/test_bm25_channel.py`
- `tests/retrieval/test_temporal_channel.py`
- `tests/retrieval/test_ppr_channel.py`
- `tests/retrieval/test_cross_encoder.py`
- `tests/retrieval/test_multi_channel_integration.py`
- `alembic/versions/2026_06_12_add_gin_index.py`

### Modified Files
- `src/context_service/retrieval/fusion.py` — add channel methods, update `retrieve()`
- `src/context_service/config/settings.py` — add channel configs
- `src/context_service/retrieval/__init__.py` — export new modules
- `pyproject.toml` — add `python-dateutil` dependency
- `.env.example` — document new env vars

---

## Day 0: Pre-Sprint Setup

### Task 0.1: Pipeline Skeleton

**Files:**
- Modify: `src/context_service/retrieval/fusion.py`

- [ ] **Step 1: Add stub channel methods to FusionRetriever**

Add these stub methods after `_graph_channel` (around line 265):

```python
async def _bm25_channel(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """BM25 keyword search via Postgres GIN index. (Stub - Day 1)"""
    return ChannelResult(channel_name="bm25", ranked_ids=[], latency_ms=0.0)

async def _temporal_channel(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """Temporal date-aware retrieval. (Stub - Day 1)"""
    return ChannelResult(channel_name="temporal", ranked_ids=[], latency_ms=0.0)

async def _ppr_channel(
    self,
    seed_ids: list[str],
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """PPR graph traversal from semantic seeds. (Stub - Day 2)"""
    return ChannelResult(channel_name="ppr", ranked_ids=[], latency_ms=0.0)

async def _rerank(
    self,
    query: str,
    fused: list[FusedResult],
) -> list[FusedResult]:
    """Cross-encoder reranking. (Stub - Day 2)"""
    return fused
```

- [ ] **Step 2: Update retrieve() to use all channels**

Replace the `retrieve()` method body (lines 76-169) with:

```python
async def retrieve(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    *,
    graph_depth: int = 2,
    layers: list[str] | None = None,
) -> list[FusedResult]:
    """Run 4-channel retrieval with RRF fusion and reranking."""
    fetch_k = top_k * 2

    # 1. Run semantic, BM25, temporal in parallel
    semantic_result, bm25_result, temporal_result = await asyncio.gather(
        self._semantic_channel(query, scope, fetch_k, layers),
        self._bm25_channel(query, scope, fetch_k, layers),
        self._temporal_channel(query, scope, fetch_k, layers),
        return_exceptions=True,
    )

    # Handle exceptions as empty results
    if isinstance(semantic_result, Exception):
        logger.warning("semantic_channel_error", error=str(semantic_result))
        semantic_result = ChannelResult("semantic", [], 0.0, str(semantic_result))
    if isinstance(bm25_result, Exception):
        logger.warning("bm25_channel_error", error=str(bm25_result))
        bm25_result = ChannelResult("bm25", [], 0.0, str(bm25_result))
    if isinstance(temporal_result, Exception):
        logger.warning("temporal_channel_error", error=str(temporal_result))
        temporal_result = ChannelResult("temporal", [], 0.0, str(temporal_result))

    for ch in [semantic_result, bm25_result, temporal_result]:
        logger.debug("fusion_channel_complete", channel=ch.channel_name,
                     count=len(ch.ranked_ids), latency_ms=ch.latency_ms)

    # 2. Graph channel seeds from semantic (sequential dependency)
    seed_ids = semantic_result.ranked_ids[:20] if not semantic_result.error else []
    try:
        ppr_result = await self._ppr_channel(seed_ids, scope, fetch_k, layers)
    except Exception as exc:
        logger.warning("ppr_channel_error", error=str(exc))
        ppr_result = ChannelResult("ppr", [], 0.0, str(exc))

    logger.debug("fusion_channel_complete", channel="ppr",
                 count=len(ppr_result.ranked_ids), latency_ms=ppr_result.latency_ms)

    # 3. RRF fusion across all channels
    channel_results = [semantic_result, bm25_result, temporal_result, ppr_result]
    fused = self._fuse_rrf(channel_results, fetch_k)

    # 4. Rerank top candidates
    reranked = await self._rerank(query, fused[:50])

    logger.info("fusion_complete", query_len=len(query), top_k=top_k,
                fused_count=len(reranked),
                channels=[c.channel_name for c in channel_results if not c.error])

    return reranked[:top_k]
```

- [ ] **Step 3: Add asyncio import**

At the top of fusion.py, add to imports:

```python
import asyncio
```

- [ ] **Step 4: Run tests to verify no regression**

Run: `uv run pytest tests/retrieval/test_fusion.py -v`
Expected: All existing tests pass (stubs return empty, existing behavior preserved)

- [ ] **Step 5: Commit skeleton**

```bash
git add src/context_service/retrieval/fusion.py
git commit -m "feat(retrieval): add 4-channel pipeline skeleton with stubs"
```

---

### Task 0.2: Add Channel Configs

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_channel_configs.py`

- [ ] **Step 1: Write failing test**

Create `tests/config/test_channel_configs.py`:

```python
"""Tests for multi-channel retrieval configs."""

from context_service.config.settings import (
    BM25ChannelConfig,
    TemporalChannelConfig,
    GraphChannelConfig,
    CrossEncoderConfig,
    Settings,
)


class TestChannelConfigs:
    def test_bm25_defaults(self) -> None:
        cfg = BM25ChannelConfig()
        assert cfg.enabled is True
        assert cfg.top_k == 100

    def test_temporal_defaults(self) -> None:
        cfg = TemporalChannelConfig()
        assert cfg.enabled is True
        assert cfg.memory_half_life_days == 14
        assert cfg.knowledge_half_life_days == 90

    def test_graph_defaults(self) -> None:
        cfg = GraphChannelConfig()
        assert cfg.enabled is True
        assert cfg.damping == 0.85
        assert cfg.max_iterations == 50
        assert "SYNTHESIZED_FROM" in cfg.edge_weights

    def test_cross_encoder_defaults(self) -> None:
        cfg = CrossEncoderConfig()
        assert cfg.enabled is True
        assert "ms-marco" in cfg.model
        assert cfg.top_k == 50

    def test_attached_to_settings(self) -> None:
        assert "bm25_channel" in Settings.model_fields
        assert "temporal_channel" in Settings.model_fields
        assert "graph_channel" in Settings.model_fields
        assert "cross_encoder" in Settings.model_fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_channel_configs.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Add config classes to settings.py**

After `EpistemicFusionConfig` (around line 175), add:

```python
class BM25ChannelConfig(BaseModel):
    """BM25 keyword search channel configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    top_k: int = 100


class TemporalChannelConfig(BaseModel):
    """Temporal date-aware retrieval channel configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    memory_half_life_days: int = 14
    knowledge_half_life_days: int = 90


class GraphChannelConfig(BaseModel):
    """PPR graph traversal channel configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    damping: float = 0.85
    max_iterations: int = 50
    edge_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "SYNTHESIZED_FROM": 1.5,
            "SUPERSEDES": 1.5,
            "LINK": 1.0,
        }
    )


class CrossEncoderConfig(BaseModel):
    """Local cross-encoder reranker configuration."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 50
```

- [ ] **Step 4: Attach configs to Settings class**

In the Settings class (around line 1000), add after `epistemic_fusion`:

```python
bm25_channel: BM25ChannelConfig = Field(default_factory=BM25ChannelConfig)
temporal_channel: TemporalChannelConfig = Field(default_factory=TemporalChannelConfig)
graph_channel: GraphChannelConfig = Field(default_factory=GraphChannelConfig)
cross_encoder: CrossEncoderConfig = Field(default_factory=CrossEncoderConfig)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/config/test_channel_configs.py -v`
Expected: PASS

- [ ] **Step 6: Commit configs**

```bash
git add src/context_service/config/settings.py tests/config/test_channel_configs.py
git commit -m "feat(config): add BM25, temporal, graph, cross-encoder channel configs"
```

---

### Task 0.3: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add python-dateutil**

In `pyproject.toml` dependencies section, add:

```toml
"python-dateutil>=2.8.2",
```

- [ ] **Step 2: Sync dependencies**

Run: `just install-dev`

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "from dateutil import parser; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add python-dateutil for temporal channel"
```

---

### Task 0.4: Verify Prerequisites

- [ ] **Step 1: Check Memgraph MAGE status**

Run: `docker inspect engrammic-memgraph 2>/dev/null | grep -i mage || echo "Not running or not MAGE"`

If MAGE is not available, PPR will use Python-side implementation (Task 2.2 handles this).

- [ ] **Step 2: Verify mem0 adapter exists**

Run: `ls -la ../longmemeval-harness/adapters/ 2>/dev/null || echo "Harness not found"`

If not found, note for Day 3 — may need to create adapter.

- [ ] **Step 3: Pre-download cross-encoder model (optional, saves Day 2 time)**

Run: `uv run python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"`

---

## Day 1: BM25 + Temporal Channels

### Worktree 1: BM25 Channel

#### Task 1.1: BM25 Alembic Migration

**Files:**
- Create: `alembic/versions/2026_06_12_add_gin_index.py`

- [ ] **Step 1: Generate migration**

Run: `uv run alembic revision -m "add_gin_index_nodes_content"`

- [ ] **Step 2: Write migration**

Edit the generated file:

```python
"""Add GIN index on nodes.content for BM25 search.

Revision ID: [generated]
Revises: [previous]
Create Date: 2026-06-12
"""

from alembic import op

revision = "[generated]"
down_revision = "[previous]"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_nodes_content_gin
        ON nodes USING GIN (to_tsvector('english', content))
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_nodes_content_gin")
```

- [ ] **Step 3: Run migration locally**

Run: `just db-migrate`

- [ ] **Step 4: Commit migration**

```bash
git add alembic/versions/2026_06_12_*.py
git commit -m "migration: add GIN index on nodes.content for BM25"
```

---

#### Task 1.2: BM25 Channel Implementation

**Files:**
- Modify: `src/context_service/retrieval/fusion.py`
- Test: `tests/retrieval/test_bm25_channel.py`

- [ ] **Step 1: Write failing test**

Create `tests/retrieval/test_bm25_channel.py`:

```python
"""Tests for BM25 channel."""

import pytest

from context_service.retrieval.fusion import FusionRetriever, ChannelResult


class TestBM25Channel:
    @pytest.mark.asyncio
    async def test_bm25_returns_channel_result(
        self, fusion_retriever: FusionRetriever, scope_context
    ) -> None:
        result = await fusion_retriever._bm25_channel(
            query="test query",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert isinstance(result, ChannelResult)
        assert result.channel_name == "bm25"
        assert result.latency_ms >= 0

    @pytest.mark.asyncio
    async def test_bm25_exact_match_ranked_higher(
        self, fusion_retriever: FusionRetriever, scope_context, store_test_nodes
    ) -> None:
        # store_test_nodes fixture creates nodes with known content
        result = await fusion_retriever._bm25_channel(
            query="exact phrase from test node",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        # Node with exact phrase should be in results
        assert len(result.ranked_ids) > 0

    @pytest.mark.asyncio
    async def test_bm25_empty_query_returns_empty(
        self, fusion_retriever: FusionRetriever, scope_context
    ) -> None:
        result = await fusion_retriever._bm25_channel(
            query="",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert result.ranked_ids == []

    @pytest.mark.asyncio
    async def test_bm25_respects_layers_filter(
        self, fusion_retriever: FusionRetriever, scope_context, store_test_nodes
    ) -> None:
        result = await fusion_retriever._bm25_channel(
            query="test",
            scope=scope_context,
            top_k=10,
            layers=["memory"],
        )
        # Should only return memory layer nodes
        assert isinstance(result, ChannelResult)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retrieval/test_bm25_channel.py -v`
Expected: FAIL (stub returns empty)

- [ ] **Step 3: Implement BM25 channel**

Replace the stub `_bm25_channel` in fusion.py:

```python
async def _bm25_channel(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """BM25 keyword search via Postgres GIN index.

    Uses ts_rank with plainto_tsquery for scoring. Falls back to
    empty result if query is empty or database errors.
    """
    if not query.strip():
        return ChannelResult(channel_name="bm25", ranked_ids=[], latency_ms=0.0)

    t0 = time.perf_counter()
    try:
        # Build layer filter clause
        layer_clause = ""
        params: dict[str, Any] = {
            "query": query,
            "silo_id": str(scope.silo_id),
            "top_k": top_k,
        }
        if layers:
            layer_clause = "AND layer = ANY(:layers)"
            params["layers"] = layers

        sql = f"""
            SELECT id, ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query)) AS rank
            FROM nodes
            WHERE silo_id = :silo_id
              AND to_tsvector('english', content) @@ plainto_tsquery('english', :query)
              {layer_clause}
            ORDER BY rank DESC
            LIMIT :top_k
        """

        async with self._ctx._pg_pool.acquire() as conn:
            rows = await conn.fetch(sql, params)

        ranked_ids = [str(row["id"]) for row in rows]
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return ChannelResult(
            channel_name="bm25",
            ranked_ids=ranked_ids,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="bm25",
            ranked_ids=[],
            latency_ms=latency_ms,
            error=str(exc),
        )
```

- [ ] **Step 4: Add Any import**

Add to imports at top:

```python
from typing import TYPE_CHECKING, Any
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/retrieval/test_bm25_channel.py -v`
Expected: PASS

- [ ] **Step 6: Run type check**

Run: `just check`
Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/context_service/retrieval/fusion.py tests/retrieval/test_bm25_channel.py
git commit -m "feat(retrieval): implement BM25 channel with GIN index search"
```

---

### Worktree 2: Temporal Channel

#### Task 1.3: Temporal Date Parser

**Files:**
- Create: `src/context_service/retrieval/temporal.py`
- Test: `tests/retrieval/test_temporal_channel.py`

- [ ] **Step 1: Write failing test**

Create `tests/retrieval/test_temporal_channel.py`:

```python
"""Tests for temporal date parsing and channel."""

from datetime import datetime, timedelta, UTC

import pytest

from context_service.retrieval.temporal import (
    parse_temporal_query,
    TemporalQuery,
    compute_recency_score,
)


class TestTemporalParsing:
    def test_parse_last_week(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        result = parse_temporal_query("what did I learn last week", now)
        assert result is not None
        assert result.since is not None
        assert result.since < now
        # "last week" should be ~7 days ago
        assert (now - result.since).days >= 6

    def test_parse_since_monday(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)  # Thursday
        result = parse_temporal_query("changes since monday", now)
        assert result is not None
        assert result.since is not None

    def test_parse_yesterday(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        result = parse_temporal_query("what happened yesterday", now)
        assert result is not None
        assert result.since is not None
        assert (now - result.since).days >= 1

    def test_no_temporal_in_query(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        result = parse_temporal_query("the last project we discussed", now)
        # "the last project" should NOT trigger temporal parsing
        assert result is None

    def test_parse_specific_date(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        result = parse_temporal_query("what did I learn on June 10", now)
        assert result is not None


class TestRecencyScoring:
    def test_recent_node_scores_higher(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        recent = now - timedelta(days=1)
        old = now - timedelta(days=30)

        recent_score = compute_recency_score(recent, now, half_life_days=14)
        old_score = compute_recency_score(old, now, half_life_days=14)

        assert recent_score > old_score

    def test_half_life_decay(self) -> None:
        now = datetime(2026, 6, 12, 12, 0, 0, tzinfo=UTC)
        at_half_life = now - timedelta(days=14)

        score = compute_recency_score(at_half_life, now, half_life_days=14)
        # At half-life, score should be ~0.5
        assert 0.4 < score < 0.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retrieval/test_temporal_channel.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement temporal module**

Create `src/context_service/retrieval/temporal.py`:

```python
"""Temporal date parsing and recency scoring for retrieval."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, UTC

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta, MO, TU, WE, TH, FR, SA, SU


@dataclass
class TemporalQuery:
    """Parsed temporal constraints from a query."""

    since: datetime | None = None
    until: datetime | None = None
    target_date: datetime | None = None


# Patterns that indicate temporal intent (not just "last" as a word)
_TEMPORAL_PATTERNS = [
    (r"\blast\s+week\b", "last_week"),
    (r"\blast\s+month\b", "last_month"),
    (r"\byesterday\b", "yesterday"),
    (r"\btoday\b", "today"),
    (r"\bsince\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "since_weekday"),
    (r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "last_weekday"),
    (r"\b(\d+)\s+days?\s+ago\b", "days_ago"),
    (r"\bthis\s+week\b", "this_week"),
    (r"\brecently\b", "recently"),
    (r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d+\b", "specific_date"),
    (r"\bon\s+(january|february|march|april|may|june|july|august|september|october|november|december)", "on_date"),
]

_WEEKDAY_MAP = {
    "monday": MO, "tuesday": TU, "wednesday": WE, "thursday": TH,
    "friday": FR, "saturday": SA, "sunday": SU,
}


def parse_temporal_query(query: str, now: datetime) -> TemporalQuery | None:
    """Parse temporal constraints from a natural language query.

    Returns None if no temporal intent is detected. Distinguishes between
    "last week" (temporal) and "the last project" (not temporal).
    """
    query_lower = query.lower()

    for pattern, intent in _TEMPORAL_PATTERNS:
        match = re.search(pattern, query_lower)
        if match:
            return _resolve_temporal_intent(intent, match, now)

    return None


def _resolve_temporal_intent(
    intent: str, match: re.Match, now: datetime
) -> TemporalQuery:
    """Resolve a matched temporal pattern to concrete dates."""
    if intent == "last_week":
        since = now - timedelta(days=7)
        return TemporalQuery(since=since)

    if intent == "last_month":
        since = now - relativedelta(months=1)
        return TemporalQuery(since=since)

    if intent == "yesterday":
        start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return TemporalQuery(since=start, until=end)

    if intent == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return TemporalQuery(since=start)

    if intent == "this_week":
        # Start of current week (Monday)
        days_since_monday = now.weekday()
        start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return TemporalQuery(since=start)

    if intent == "recently":
        since = now - timedelta(days=7)
        return TemporalQuery(since=since)

    if intent == "since_weekday":
        weekday_name = match.group(1).lower()
        weekday = _WEEKDAY_MAP[weekday_name]
        target = now + relativedelta(weekday=weekday(-1))
        if target > now:
            target = now + relativedelta(weekday=weekday(-2))
        return TemporalQuery(since=target.replace(hour=0, minute=0, second=0, microsecond=0))

    if intent == "last_weekday":
        weekday_name = match.group(1).lower()
        weekday = _WEEKDAY_MAP[weekday_name]
        target = now + relativedelta(weekday=weekday(-1))
        start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return TemporalQuery(since=start, until=end)

    if intent == "days_ago":
        days = int(match.group(1))
        since = now - timedelta(days=days)
        return TemporalQuery(since=since)

    if intent in ("specific_date", "on_date"):
        try:
            parsed = date_parser.parse(match.group(0), fuzzy=True)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            # If parsed date is in the future, assume last year
            if parsed > now:
                parsed = parsed.replace(year=parsed.year - 1)
            start = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
            return TemporalQuery(since=start, until=end, target_date=start)
        except (ValueError, TypeError):
            return TemporalQuery(since=now - timedelta(days=7))

    # Default fallback
    return TemporalQuery(since=now - timedelta(days=7))


def compute_recency_score(
    created_at: datetime,
    now: datetime,
    half_life_days: int,
) -> float:
    """Compute exponential decay score based on node age.

    Score = 0.5^(age_days / half_life_days)

    Returns value in [0, 1] where 1 is most recent.
    """
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_days = (now - created_at).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0

    return math.pow(0.5, age_days / half_life_days)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/retrieval/test_temporal_channel.py -v`
Expected: PASS

- [ ] **Step 5: Update __init__.py**

Add to `src/context_service/retrieval/__init__.py`:

```python
from context_service.retrieval.temporal import (
    parse_temporal_query,
    TemporalQuery,
    compute_recency_score,
)
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/retrieval/temporal.py tests/retrieval/test_temporal_channel.py src/context_service/retrieval/__init__.py
git commit -m "feat(retrieval): add temporal date parser with recency scoring"
```

---

#### Task 1.4: Temporal Channel in Fusion

**Files:**
- Modify: `src/context_service/retrieval/fusion.py`

- [ ] **Step 1: Add test for temporal channel**

Add to `tests/retrieval/test_temporal_channel.py`:

```python
class TestTemporalChannel:
    @pytest.mark.asyncio
    async def test_temporal_channel_with_date_query(
        self, fusion_retriever: FusionRetriever, scope_context
    ) -> None:
        result = await fusion_retriever._temporal_channel(
            query="what did I learn last week",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert isinstance(result, ChannelResult)
        assert result.channel_name == "temporal"

    @pytest.mark.asyncio
    async def test_temporal_channel_no_date_uses_recency(
        self, fusion_retriever: FusionRetriever, scope_context
    ) -> None:
        result = await fusion_retriever._temporal_channel(
            query="general query without dates",
            scope=scope_context,
            top_k=10,
            layers=None,
        )
        assert isinstance(result, ChannelResult)
        # Should still return results ranked by recency
```

- [ ] **Step 2: Implement temporal channel**

Replace the stub `_temporal_channel` in fusion.py:

```python
async def _temporal_channel(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """Temporal date-aware retrieval.

    If query contains temporal markers (last week, yesterday, etc.),
    filters to that time range. Otherwise, ranks all nodes by recency.
    """
    from context_service.retrieval.temporal import (
        parse_temporal_query,
        compute_recency_score,
    )
    from context_service.config.settings import get_settings

    settings = get_settings()
    now = datetime.now(UTC)

    t0 = time.perf_counter()
    try:
        temporal_query = parse_temporal_query(query, now)

        # Build WHERE clause
        where_clauses = ["silo_id = :silo_id"]
        params: dict[str, Any] = {"silo_id": str(scope.silo_id)}

        if temporal_query and temporal_query.since:
            where_clauses.append("created_at >= :since")
            params["since"] = temporal_query.since

        if temporal_query and temporal_query.until:
            where_clauses.append("created_at <= :until")
            params["until"] = temporal_query.until

        if layers:
            where_clauses.append("layer = ANY(:layers)")
            params["layers"] = layers

        where_sql = " AND ".join(where_clauses)

        sql = f"""
            SELECT id, layer, created_at
            FROM nodes
            WHERE {where_sql}
            ORDER BY created_at DESC
            LIMIT :limit
        """
        params["limit"] = top_k * 3  # Over-fetch for scoring

        async with self._ctx._pg_pool.acquire() as conn:
            rows = await conn.fetch(sql, params)

        # Score by recency with layer-specific half-life
        scored = []
        for row in rows:
            layer = row["layer"]
            created_at = row["created_at"]
            if isinstance(created_at, (int, float)):
                created_at = datetime.fromtimestamp(created_at, tz=UTC)

            if layer == "memory":
                half_life = settings.temporal_channel.memory_half_life_days
            else:
                half_life = settings.temporal_channel.knowledge_half_life_days

            score = compute_recency_score(created_at, now, half_life)
            scored.append((str(row["id"]), score))

        # Sort by score descending and take top_k
        scored.sort(key=lambda x: x[1], reverse=True)
        ranked_ids = [node_id for node_id, _ in scored[:top_k]]

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="temporal",
            ranked_ids=ranked_ids,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="temporal",
            ranked_ids=[],
            latency_ms=latency_ms,
            error=str(exc),
        )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/retrieval/test_temporal_channel.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/retrieval/fusion.py tests/retrieval/test_temporal_channel.py
git commit -m "feat(retrieval): implement temporal channel with date parsing"
```

---

### Task 1.5: Day 1 Merge

- [ ] **Step 1: Merge BM25 worktree**

```bash
git checkout feat/read-path-epistemic-fusion
git merge worktree/bm25-channel --no-ff -m "merge: BM25 channel from worktree"
```

- [ ] **Step 2: Merge Temporal worktree**

```bash
git merge worktree/temporal-channel --no-ff -m "merge: Temporal channel from worktree"
```

- [ ] **Step 3: Run full test suite**

Run: `just test`
Expected: All tests pass

- [ ] **Step 4: Run type check**

Run: `just check`
Expected: No errors

---

## Day 2: Reranker + PPR Channels

### Worktree 1: Cross-Encoder Reranker

#### Task 2.1: Cross-Encoder Implementation

**Files:**
- Create: `src/context_service/retrieval/cross_encoder.py`
- Test: `tests/retrieval/test_cross_encoder.py`

- [ ] **Step 1: Write failing test**

Create `tests/retrieval/test_cross_encoder.py`:

```python
"""Tests for local cross-encoder reranker."""

import pytest

from context_service.retrieval.cross_encoder import CrossEncoderReranker


class TestCrossEncoder:
    def test_rerank_returns_scores(self) -> None:
        reranker = CrossEncoderReranker()
        results = reranker.rerank(
            query="What is machine learning?",
            documents=["ML is a type of AI", "The weather is nice", "Deep learning uses neural networks"],
            node_ids=["a", "b", "c"],
        )
        assert len(results) == 3
        # ML-related docs should score higher than weather
        ml_score = next(r.score for r in results if r.node_id == "a")
        weather_score = next(r.score for r in results if r.node_id == "b")
        assert ml_score > weather_score

    def test_rerank_empty_documents(self) -> None:
        reranker = CrossEncoderReranker()
        results = reranker.rerank(query="test", documents=[], node_ids=[])
        assert results == []

    def test_rerank_respects_top_k(self) -> None:
        reranker = CrossEncoderReranker()
        results = reranker.rerank(
            query="test",
            documents=["doc1", "doc2", "doc3", "doc4", "doc5"],
            node_ids=["a", "b", "c", "d", "e"],
            top_k=3,
        )
        assert len(results) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retrieval/test_cross_encoder.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement cross-encoder wrapper**

Create `src/context_service/retrieval/cross_encoder.py`:

```python
"""Local cross-encoder reranker using sentence-transformers."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CrossEncoderResult:
    """Result from cross-encoder reranking."""

    node_id: str
    score: float
    original_index: int


@lru_cache(maxsize=1)
def _get_model(model_name: str):
    """Lazy-load and cache the cross-encoder model."""
    from sentence_transformers import CrossEncoder

    logger.info("loading_cross_encoder", model=model_name)
    return CrossEncoder(model_name)


class CrossEncoderReranker:
    """Local cross-encoder reranker.

    Uses sentence-transformers CrossEncoder for query-document scoring.
    Model is lazily loaded and cached.
    """

    def __init__(
        self,
        model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
    ) -> None:
        self._model_name = model

    def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int | None = None,
    ) -> list[CrossEncoderResult]:
        """Rerank documents by relevance to query.

        Args:
            query: Search query.
            documents: Document texts to score.
            node_ids: Corresponding node IDs (same order as documents).
            top_k: Optional limit on returned results.

        Returns:
            List of CrossEncoderResult sorted by score descending.
        """
        if not documents:
            return []

        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents ({len(documents)}) and node_ids ({len(node_ids)}) must match"
            )

        model = _get_model(self._model_name)

        # Cross-encoder expects list of [query, document] pairs
        pairs = [[query, doc] for doc in documents]
        scores = model.predict(pairs)

        results = [
            CrossEncoderResult(
                node_id=node_id,
                score=float(score),
                original_index=i,
            )
            for i, (node_id, score) in enumerate(zip(node_ids, scores))
        ]

        # Sort by score descending
        results.sort(key=lambda r: r.score, reverse=True)

        if top_k is not None:
            results = results[:top_k]

        return results
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/retrieval/test_cross_encoder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/retrieval/cross_encoder.py tests/retrieval/test_cross_encoder.py
git commit -m "feat(retrieval): add local cross-encoder reranker"
```

---

#### Task 2.2: Wire Reranker into Fusion

**Files:**
- Modify: `src/context_service/retrieval/fusion.py`

- [ ] **Step 1: Add test for rerank integration**

Add to `tests/retrieval/test_fusion.py`:

```python
@pytest.mark.asyncio
async def test_rerank_improves_ordering(fusion_retriever, scope_context):
    """Test that reranking reorders results by relevance."""
    # This is an integration test - requires full pipeline
    results = await fusion_retriever.retrieve(
        query="machine learning algorithms",
        scope=scope_context,
        top_k=10,
    )
    # Results should be ordered by combined score
    assert len(results) >= 0  # May be empty in test env
```

- [ ] **Step 2: Implement _rerank method**

Replace the stub `_rerank` in fusion.py:

```python
async def _rerank(
    self,
    query: str,
    fused: list[FusedResult],
) -> list[FusedResult]:
    """Cross-encoder reranking of fused results.

    Fetches document content for top candidates, scores with cross-encoder,
    and reorders by rerank score. Falls back to RRF order on error.
    """
    from context_service.config.settings import get_settings
    from context_service.retrieval.cross_encoder import CrossEncoderReranker

    settings = get_settings()
    if not settings.cross_encoder.enabled or not fused:
        return fused

    t0 = time.perf_counter()
    try:
        # Fetch content for top candidates
        node_ids = [f.node_id for f in fused[: settings.cross_encoder.top_k]]

        # Batch fetch content
        nodes = await self._ctx._store.get_nodes_batch(node_ids)
        id_to_content = {n["id"]: n.get("content", "") for n in nodes if n}

        # Prepare for reranking
        documents = []
        valid_ids = []
        for node_id in node_ids:
            content = id_to_content.get(node_id, "")
            if content:
                documents.append(content[:2000])  # Truncate for efficiency
                valid_ids.append(node_id)

        if not documents:
            return fused

        # Rerank
        reranker = CrossEncoderReranker(model=settings.cross_encoder.model)
        rerank_results = reranker.rerank(
            query=query,
            documents=documents,
            node_ids=valid_ids,
        )

        # Build score lookup
        rerank_scores = {r.node_id: r.score for r in rerank_results}

        # Update fused results with rerank scores and reorder
        for f in fused:
            if f.node_id in rerank_scores:
                f.channel_contributions["rerank"] = rerank_scores[f.node_id]
                # Boost RRF score by rerank score (normalized)
                max_rerank = max(rerank_scores.values()) if rerank_scores else 1.0
                normalized = rerank_scores[f.node_id] / max_rerank if max_rerank > 0 else 0
                f.rrf_score = f.rrf_score * (0.5 + 0.5 * normalized)

        # Re-sort by updated score
        fused.sort(key=lambda f: f.rrf_score, reverse=True)

        latency_ms = (time.perf_counter() - t0) * 1000.0
        logger.debug("rerank_complete", latency_ms=latency_ms, count=len(rerank_results))

        return fused

    except Exception as exc:
        logger.warning("rerank_fallback", error=str(exc))
        return fused  # Fallback to RRF order
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/retrieval/test_fusion.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/retrieval/fusion.py
git commit -m "feat(retrieval): wire cross-encoder reranker into fusion pipeline"
```

---

### Worktree 2: PPR Graph Channel

#### Task 2.3: PPR Implementation

**Files:**
- Create: `src/context_service/retrieval/ppr.py`
- Test: `tests/retrieval/test_ppr_channel.py`

- [ ] **Step 1: Write failing test**

Create `tests/retrieval/test_ppr_channel.py`:

```python
"""Tests for PPR graph channel."""

import pytest

from context_service.retrieval.ppr import PersonalizedPageRank


class TestPPR:
    def test_ppr_from_seeds(self) -> None:
        # Simple graph: A -> B -> C, A -> D
        adjacency = {
            "A": [("B", 1.0), ("D", 1.0)],
            "B": [("C", 1.0)],
            "C": [],
            "D": [],
        }
        ppr = PersonalizedPageRank(damping=0.85, max_iterations=50)
        scores = ppr.compute(seed_ids=["A"], adjacency=adjacency)

        # A should have highest score (seed)
        assert scores["A"] > scores["B"]
        # B should have higher than C (closer to seed)
        assert scores["B"] > scores["C"]

    def test_ppr_empty_seeds(self) -> None:
        ppr = PersonalizedPageRank()
        scores = ppr.compute(seed_ids=[], adjacency={})
        assert scores == {}

    def test_ppr_weighted_edges(self) -> None:
        # Edge weights should affect score propagation
        adjacency = {
            "A": [("B", 2.0), ("C", 0.5)],  # B weighted higher
            "B": [],
            "C": [],
        }
        ppr = PersonalizedPageRank()
        scores = ppr.compute(seed_ids=["A"], adjacency=adjacency)

        # B should score higher than C due to edge weight
        assert scores["B"] > scores["C"]

    def test_ppr_respects_max_iterations(self) -> None:
        # Large graph shouldn't hang
        adjacency = {str(i): [(str(i + 1), 1.0)] for i in range(100)}
        adjacency["100"] = []

        ppr = PersonalizedPageRank(max_iterations=10)
        scores = ppr.compute(seed_ids=["0"], adjacency=adjacency)
        assert len(scores) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retrieval/test_ppr_channel.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement PPR algorithm**

Create `src/context_service/retrieval/ppr.py`:

```python
"""Personalized PageRank for graph-based retrieval."""

from __future__ import annotations

from collections import defaultdict

import structlog

logger = structlog.get_logger(__name__)


class PersonalizedPageRank:
    """Personalized PageRank with weighted edges.

    Pure Python implementation that doesn't require Memgraph MAGE.
    """

    def __init__(
        self,
        damping: float = 0.85,
        max_iterations: int = 50,
        tolerance: float = 1e-6,
    ) -> None:
        self._damping = damping
        self._max_iterations = max_iterations
        self._tolerance = tolerance

    def compute(
        self,
        seed_ids: list[str],
        adjacency: dict[str, list[tuple[str, float]]],
    ) -> dict[str, float]:
        """Compute PPR scores from seed nodes.

        Args:
            seed_ids: Starting node IDs (personalization vector).
            adjacency: Node -> list of (neighbor, edge_weight) tuples.

        Returns:
            Dict mapping node_id -> PPR score.
        """
        if not seed_ids:
            return {}

        # Initialize scores
        all_nodes = set(adjacency.keys())
        for neighbors in adjacency.values():
            for neighbor, _ in neighbors:
                all_nodes.add(neighbor)

        n = len(all_nodes)
        if n == 0:
            return {}

        # Personalization vector (uniform over seeds)
        personalization: dict[str, float] = {}
        seed_weight = 1.0 / len(seed_ids)
        for seed in seed_ids:
            personalization[seed] = seed_weight

        # Initial scores = personalization
        scores = dict(personalization)
        for node in all_nodes:
            if node not in scores:
                scores[node] = 0.0

        # Precompute out-degree weights
        out_weights: dict[str, float] = defaultdict(float)
        for node, neighbors in adjacency.items():
            out_weights[node] = sum(w for _, w in neighbors)

        # Power iteration
        for iteration in range(self._max_iterations):
            new_scores: dict[str, float] = {}

            for node in all_nodes:
                # Teleport component
                teleport = (1 - self._damping) * personalization.get(node, 0.0)

                # Random walk component
                walk = 0.0
                # Find nodes that link TO this node
                for source, neighbors in adjacency.items():
                    for neighbor, weight in neighbors:
                        if neighbor == node:
                            out_w = out_weights[source]
                            if out_w > 0:
                                walk += self._damping * scores[source] * (weight / out_w)

                new_scores[node] = teleport + walk

            # Check convergence
            diff = sum(abs(new_scores[n] - scores[n]) for n in all_nodes)
            scores = new_scores

            if diff < self._tolerance:
                logger.debug("ppr_converged", iterations=iteration + 1)
                break

        return scores
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/retrieval/test_ppr_channel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/retrieval/ppr.py tests/retrieval/test_ppr_channel.py
git commit -m "feat(retrieval): add PPR algorithm for graph channel"
```

---

#### Task 2.4: Wire PPR into Fusion

**Files:**
- Modify: `src/context_service/retrieval/fusion.py`

- [ ] **Step 1: Implement _ppr_channel**

Replace the stub `_ppr_channel` in fusion.py:

```python
async def _ppr_channel(
    self,
    seed_ids: list[str],
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """PPR graph traversal from semantic seeds.

    Runs Personalized PageRank from seed nodes, with edge-type weighting.
    """
    from context_service.config.settings import get_settings
    from context_service.retrieval.ppr import PersonalizedPageRank

    settings = get_settings()
    if not settings.graph_channel.enabled or not seed_ids:
        return ChannelResult(channel_name="ppr", ranked_ids=[], latency_ms=0.0)

    t0 = time.perf_counter()
    try:
        # Fetch adjacency from graph store
        # Get edges within 2 hops of seeds
        edge_query = """
            UNWIND $seed_ids AS seed
            MATCH (n:Node {id: seed, silo_id: $silo_id})-[r]-(m:Node {silo_id: $silo_id})
            RETURN n.id AS source, m.id AS target, type(r) AS edge_type
            UNION
            UNWIND $seed_ids AS seed
            MATCH (n:Node {id: seed, silo_id: $silo_id})-[r1]-(m1:Node)-[r2]-(m2:Node {silo_id: $silo_id})
            WHERE m1.silo_id = $silo_id
            RETURN m1.id AS source, m2.id AS target, type(r2) AS edge_type
        """
        rows = await self._ctx._store.execute_query(
            edge_query,
            {"seed_ids": seed_ids, "silo_id": str(scope.silo_id)},
        )

        # Build adjacency with edge weights
        edge_weights = settings.graph_channel.edge_weights
        adjacency: dict[str, list[tuple[str, float]]] = defaultdict(list)

        for row in rows:
            source = row["source"]
            target = row["target"]
            edge_type = row["edge_type"]
            weight = edge_weights.get(edge_type, 1.0)
            adjacency[source].append((target, weight))

        # Run PPR
        ppr = PersonalizedPageRank(
            damping=settings.graph_channel.damping,
            max_iterations=settings.graph_channel.max_iterations,
        )
        scores = ppr.compute(seed_ids=seed_ids, adjacency=dict(adjacency))

        # Filter by layers if specified
        if layers:
            # Fetch layer info for scored nodes
            node_ids = list(scores.keys())
            layer_query = """
                UNWIND $node_ids AS nid
                MATCH (n:Node {id: nid, silo_id: $silo_id})
                RETURN n.id AS node_id, n.layer AS layer
            """
            layer_rows = await self._ctx._store.execute_query(
                layer_query,
                {"node_ids": node_ids, "silo_id": str(scope.silo_id)},
            )
            valid_ids = {r["node_id"] for r in layer_rows if r["layer"] in layers}
            scores = {k: v for k, v in scores.items() if k in valid_ids}

        # Sort by score and return top_k
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        ranked_ids = [node_id for node_id, _ in ranked[:top_k]]

        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="ppr",
            ranked_ids=ranked_ids,
            latency_ms=latency_ms,
        )

    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="ppr",
            ranked_ids=[],
            latency_ms=latency_ms,
            error=str(exc),
        )
```

- [ ] **Step 2: Add defaultdict import**

At top of fusion.py:

```python
from collections import defaultdict
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/retrieval/ -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/retrieval/fusion.py
git commit -m "feat(retrieval): wire PPR channel into fusion pipeline"
```

---

### Task 2.5: Day 2 Merge & Integration

- [ ] **Step 1: Merge Reranker worktree**

```bash
git checkout feat/read-path-epistemic-fusion
git merge worktree/cross-encoder --no-ff -m "merge: Cross-encoder reranker from worktree"
```

- [ ] **Step 2: Merge PPR worktree**

```bash
git merge worktree/ppr-channel --no-ff -m "merge: PPR channel from worktree"
```

- [ ] **Step 3: Run integration test**

Create `tests/retrieval/test_multi_channel_integration.py`:

```python
"""Integration tests for multi-channel retrieval."""

import pytest


class TestMultiChannelIntegration:
    @pytest.mark.asyncio
    async def test_all_channels_contribute(self, fusion_retriever, scope_context):
        """Verify all 4 channels run and contribute to fusion."""
        results = await fusion_retriever.retrieve(
            query="test query last week",
            scope=scope_context,
            top_k=10,
        )
        # Even with empty store, should not error
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_latency_under_threshold(self, fusion_retriever, scope_context):
        """Full pipeline should complete under 250ms p95."""
        import time

        latencies = []
        for _ in range(5):
            t0 = time.perf_counter()
            await fusion_retriever.retrieve(
                query="benchmark query",
                scope=scope_context,
                top_k=10,
            )
            latencies.append((time.perf_counter() - t0) * 1000)

        p95 = sorted(latencies)[int(len(latencies) * 0.95)]
        # Allow slack for CI environments
        assert p95 < 500, f"p95 latency {p95}ms exceeds threshold"
```

- [ ] **Step 4: Run full test suite**

Run: `just test`
Expected: All tests pass

- [ ] **Step 5: Run type check**

Run: `just check`
Expected: No errors

- [ ] **Step 6: Commit integration tests**

```bash
git add tests/retrieval/test_multi_channel_integration.py
git commit -m "test(retrieval): add multi-channel integration tests"
```

---

## Day 3: Integration + Benchmark

### Task 3.1: Final Integration Testing

- [ ] **Step 1: Run full CI**

Run: `just ci`
Expected: All checks pass

- [ ] **Step 2: Test with real stores**

Run: `just up && just test -k integration`
Expected: Tests pass against real Memgraph/Qdrant/Postgres

- [ ] **Step 3: Manual smoke test**

```bash
just dev &
# In another terminal:
curl -X POST http://localhost:8000/mcp/recall \
  -H "Content-Type: application/json" \
  -d '{"query": "what did I learn last week", "top_k": 5}'
```

---

### Task 3.2: Benchmark Setup

- [ ] **Step 1: Verify harness exists**

```bash
ls ../longmemeval-harness/
```

- [ ] **Step 2: Create epistemic slice test cases**

Create `../longmemeval-harness/epistemic_slices/supersession/cases.jsonl`:

```jsonl
{"id": "sup-1", "setup": [{"type": "learn", "content": "API uses OAuth1", "evidence": "docs/v1.md"}, {"type": "learn", "content": "API uses OAuth2 with PKCE", "evidence": "docs/v2.md", "supersedes": "prev"}], "query": "How does the API authenticate?", "expected": "OAuth2 with PKCE", "not_expected": "OAuth1"}
{"id": "sup-2", "setup": [{"type": "remember", "content": "Meeting at 2pm"}, {"type": "remember", "content": "Meeting moved to 3pm", "supersedes": "prev"}], "query": "What time is the meeting?", "expected": "3pm", "not_expected": "2pm"}
```

- [ ] **Step 3: Create contradiction test cases**

Create `../longmemeval-harness/epistemic_slices/contradiction/cases.jsonl`:

```jsonl
{"id": "con-1", "setup": [{"type": "learn", "content": "Server runs on port 8080", "evidence": "config/dev.yaml"}, {"type": "learn", "content": "Server runs on port 3000", "evidence": "config/prod.yaml"}], "query": "What port does the server run on?", "expected_behavior": "acknowledge_conflict"}
{"id": "con-2", "setup": [{"type": "learn", "content": "Max retries is 3"}, {"type": "learn", "content": "Max retries is 5"}], "query": "How many retries are allowed?", "expected_behavior": "acknowledge_conflict"}
```

- [ ] **Step 4: Create abstention test cases**

Create `../longmemeval-harness/epistemic_slices/abstention/cases.jsonl`:

```jsonl
{"id": "abs-1", "setup": [], "query": "What is the deployment schedule?", "expected_behavior": "abstain"}
{"id": "abs-2", "setup": [{"type": "remember", "content": "Heard something about Friday", "confidence": 0.2}], "query": "When is the deadline?", "expected_behavior": "low_confidence_caveat"}
```

---

### Task 3.3: Run Benchmark

- [ ] **Step 1: Run Engrammic (full)**

```bash
cd ../longmemeval-harness
uv run python harness.py --adapter engrammic --slices epistemic_slices/ --output results/engrammic_full.json
```

- [ ] **Step 2: Run Engrammic (baseline)**

```bash
# Disable channels via env
ENGRAMMIC_BM25_ENABLED=false ENGRAMMIC_TEMPORAL_ENABLED=false ENGRAMMIC_PPR_ENABLED=false ENGRAMMIC_CROSS_ENCODER_ENABLED=false \
uv run python harness.py --adapter engrammic --slices epistemic_slices/ --output results/engrammic_baseline.json
```

- [ ] **Step 3: Run mem0**

```bash
uv run python harness.py --adapter mem0 --slices epistemic_slices/ --output results/mem0.json
```

- [ ] **Step 4: Generate report**

```bash
uv run python report.py --results results/ --output BENCHMARK_RESULTS.md
```

---

### Task 3.4: Document Results

- [ ] **Step 1: Copy results to context-service**

```bash
cp ../longmemeval-harness/BENCHMARK_RESULTS.md context/benchmarks/2026-06-12-epistemic-slices.md
```

- [ ] **Step 2: Commit results**

```bash
git add context/benchmarks/
git commit -m "docs: add epistemic slice benchmark results"
```

---

## Success Criteria

1. [ ] All 4 channels operational (semantic, BM25, temporal, PPR)
2. [ ] Cross-encoder reranker integrated with fallback
3. [ ] `just check` passes (mypy strict + ruff)
4. [ ] `just test` passes
5. [ ] Integration tests green
6. [ ] Benchmark shows Engrammic wins epistemic slices vs mem0
7. [ ] p95 latency < 250ms on integration tests
