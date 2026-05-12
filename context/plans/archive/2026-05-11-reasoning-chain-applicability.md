# Reasoning Chain Applicability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable reasoning chain reuse by matching cached chains to new queries via three-layer applicability matching (query intent, step similarity, evidence accessibility).

**Architecture:** Three-layer funnel: Layer 1 filters by query embedding similarity (Qdrant ANN), Layer 2 compares step embeddings via DTW, Layer 3 checks evidence accessibility. Write path embeds query sync, steps async. Background Dagster job tracks implicit usefulness feedback.

**Tech Stack:** dtaidistance (DTW), SQLAlchemy/Postgres (feedback storage), Qdrant (embeddings), Dagster (feedback job)

**Spec:** `context/specs/reasoning-chain-applicability.md`

---

## File Structure

| File | Responsibility |
|------|----------------|
| `pyproject.toml` | Add dtaidistance dependency |
| `config/reasoning_chain.yaml` | Thresholds, top_k, latency guards |
| `src/context_service/models/postgres/chain_feedback.py` | ChainDelivery and ChainFeedback SQLAlchemy models |
| `src/context_service/engine/dtw.py` | DTW wrapper using dtaidistance |
| `src/context_service/engine/chain_applicability.py` | find_applicable_chain with three-layer matching |
| `src/context_service/mcp/tools/context_store.py` | Attach query_embedding at chain creation |
| `src/context_service/pipelines/assets/chain_feedback.py` | Dagster asset for usefulness signals |
| `src/context_service/telemetry/metrics.py` | Retrieval and feedback metrics |

---

## Task 1: Add dtaidistance dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency to pyproject.toml**

```toml
# In [project.dependencies], add:
"dtaidistance>=2.3.0",
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync --all-extras`
Expected: Successfully installed dtaidistance

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "from dtaidistance import dtw_ndim; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add dtaidistance for reasoning chain DTW matching"
```

---

## Task 2: Add configuration file

**Files:**
- Create: `config/reasoning_chain.yaml`

- [ ] **Step 1: Create config file**

```yaml
# config/reasoning_chain.yaml
reasoning_chain_matching:
  query_threshold_cold: 0.95
  query_threshold_warm: 0.88
  step_threshold: 0.85
  top_k_candidates: 5
  dtw_latency_warn_ms: 50
  dtw_latency_abort_ms: 100

reasoning_chain:
  model: ${EAG_EMBEDDING_MODEL}  # inherit from main embedding model

chain_feedback:
  evaluation_delay_minutes: 5
  min_subsequent_steps: 3
  max_wait_minutes: 30
```

- [ ] **Step 2: Commit**

```bash
git add config/reasoning_chain.yaml
git commit -m "config: add reasoning chain matching configuration"
```

---

## Task 3: Create Postgres models for feedback tracking

**Files:**
- Create: `src/context_service/models/postgres/chain_feedback.py`
- Modify: `src/context_service/models/postgres/__init__.py`
- Test: `tests/models/postgres/test_chain_feedback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/models/postgres/test_chain_feedback.py
"""Tests for chain feedback Postgres models."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from context_service.models.postgres.chain_feedback import ChainDelivery, ChainFeedback


@pytest.mark.asyncio
async def test_chain_delivery_create(pg_session: AsyncSession) -> None:
    """ChainDelivery can be created and queried."""
    delivery = ChainDelivery(
        session_id=uuid4(),
        chain_id=uuid4(),
        query="test query",
        similarity_score=0.92,
    )
    pg_session.add(delivery)
    await pg_session.commit()

    result = await pg_session.execute(
        select(ChainDelivery).where(ChainDelivery.id == delivery.id)
    )
    row = result.scalar_one()
    assert row.query == "test query"
    assert row.similarity_score == 0.92


@pytest.mark.asyncio
async def test_chain_delivery_null_similarity(pg_session: AsyncSession) -> None:
    """ChainDelivery allows null similarity_score for cold-start."""
    delivery = ChainDelivery(
        session_id=uuid4(),
        chain_id=uuid4(),
        query="cold start query",
        similarity_score=None,
    )
    pg_session.add(delivery)
    await pg_session.commit()

    result = await pg_session.execute(
        select(ChainDelivery).where(ChainDelivery.id == delivery.id)
    )
    row = result.scalar_one()
    assert row.similarity_score is None


@pytest.mark.asyncio
async def test_chain_feedback_create(pg_session: AsyncSession) -> None:
    """ChainFeedback can be created with signal."""
    feedback = ChainFeedback(
        chain_id=uuid4(),
        signal="useful",
    )
    pg_session.add(feedback)
    await pg_session.commit()

    result = await pg_session.execute(
        select(ChainFeedback).where(ChainFeedback.id == feedback.id)
    )
    row = result.scalar_one()
    assert row.signal == "useful"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/models/postgres/test_chain_feedback.py -v`
Expected: FAIL with "cannot import name 'ChainDelivery'"

- [ ] **Step 3: Create the models**

```python
# src/context_service/models/postgres/chain_feedback.py
"""Chain delivery and feedback tracking models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Float, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ChainDelivery(Base):
    """Tracks when a reasoning chain is returned to an agent."""

    __tablename__ = "chain_delivery"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    session_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    delivered_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("ix_chain_delivery_session_id", "session_id"),
        Index("ix_chain_delivery_delivered_at", "delivered_at"),
    )


class ChainFeedback(Base):
    """Stores usefulness signals for delivered chains."""

    __tablename__ = "chain_feedback"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    signal: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (Index("ix_chain_feedback_chain_id", "chain_id"),)
```

- [ ] **Step 4: Export from __init__.py**

```python
# Add to src/context_service/models/postgres/__init__.py
from context_service.models.postgres.chain_feedback import ChainDelivery, ChainFeedback

__all__ = [
    # ... existing exports ...
    "ChainDelivery",
    "ChainFeedback",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/models/postgres/test_chain_feedback.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/models/postgres/chain_feedback.py \
        src/context_service/models/postgres/__init__.py \
        tests/models/postgres/test_chain_feedback.py
git commit -m "feat: add ChainDelivery and ChainFeedback Postgres models"
```

---

## Task 4: Generate Alembic migration

**Files:**
- Create: `alembic/versions/xxxx_add_chain_feedback_tables.py`

- [ ] **Step 1: Generate migration**

Run: `uv run alembic revision --autogenerate -m "add chain feedback tables"`
Expected: New migration file created in `alembic/versions/`

- [ ] **Step 2: Review migration**

Open the generated migration and verify it includes:
- `chain_delivery` table with correct columns and indexes
- `chain_feedback` table with correct columns and indexes

- [ ] **Step 3: Apply migration (dev)**

Run: `uv run alembic upgrade head`
Expected: Tables created successfully

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "migration: add chain_delivery and chain_feedback tables"
```

---

## Task 5: Create DTW wrapper

**Files:**
- Create: `src/context_service/engine/dtw.py`
- Test: `tests/engine/test_dtw.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_dtw.py
"""Tests for DTW similarity wrapper."""

import pytest

from context_service.engine.dtw import dtw_similarity


def test_dtw_similarity_identical() -> None:
    """Identical sequences have similarity 1.0."""
    steps_a = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    steps_b = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    
    similarity = dtw_similarity(steps_a, steps_b)
    assert similarity == pytest.approx(1.0, abs=0.01)


def test_dtw_similarity_different() -> None:
    """Different sequences have lower similarity."""
    steps_a = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    steps_b = [[0.9, 0.8, 0.7], [0.6, 0.5, 0.4]]
    
    similarity = dtw_similarity(steps_a, steps_b)
    assert 0.0 < similarity < 0.5


def test_dtw_similarity_different_lengths() -> None:
    """DTW handles sequences of different lengths."""
    steps_a = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    steps_b = [[0.1, 0.2], [0.5, 0.6]]
    
    similarity = dtw_similarity(steps_a, steps_b)
    assert 0.5 < similarity < 1.0


def test_dtw_similarity_empty() -> None:
    """Empty sequences return 0.0 similarity."""
    assert dtw_similarity([], []) == 0.0
    assert dtw_similarity([[0.1, 0.2]], []) == 0.0
    assert dtw_similarity([], [[0.1, 0.2]]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_dtw.py -v`
Expected: FAIL with "cannot import name 'dtw_similarity'"

- [ ] **Step 3: Implement DTW wrapper**

```python
# src/context_service/engine/dtw.py
"""Dynamic Time Warping wrapper for step embedding comparison."""

from __future__ import annotations

import numpy as np
from dtaidistance import dtw_ndim


def dtw_similarity(
    steps_a: list[list[float]],
    steps_b: list[list[float]],
) -> float:
    """Compute similarity between two step embedding sequences using DTW.
    
    Args:
        steps_a: First sequence of step embeddings.
        steps_b: Second sequence of step embeddings.
        
    Returns:
        Similarity score between 0.0 and 1.0.
    """
    if not steps_a or not steps_b:
        return 0.0
    
    arr_a = np.array(steps_a, dtype=np.float64)
    arr_b = np.array(steps_b, dtype=np.float64)
    
    distance = dtw_ndim.distance(arr_a, arr_b)
    
    return 1.0 / (1.0 + distance)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_dtw.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/dtw.py tests/engine/test_dtw.py
git commit -m "feat: add DTW similarity wrapper for step embedding comparison"
```

---

## Task 6: Add retrieval metrics

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`
- Test: `tests/telemetry/test_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/telemetry/test_metrics.py (or create if doesn't exist)

def test_record_chain_lookup_exists() -> None:
    """record_chain_lookup function exists and is callable."""
    from context_service.telemetry.metrics import record_chain_lookup
    
    # Should not raise
    record_chain_lookup(
        hit=True,
        layer_reached=3,
        similarity_score=0.92,
        cold_start=False,
        latency_ms=85.0,
    )


def test_record_chain_feedback_exists() -> None:
    """record_chain_feedback function exists and is callable."""
    from context_service.telemetry.metrics import record_chain_feedback
    
    # Should not raise
    record_chain_feedback(signal="useful")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/telemetry/test_metrics.py::test_record_chain_lookup_exists -v`
Expected: FAIL with "cannot import name 'record_chain_lookup'"

- [ ] **Step 3: Add metrics instruments and functions**

Add to `src/context_service/telemetry/metrics.py`:

```python
# After existing instrument declarations (around line 26)
_chain_lookup_counter: metrics.Counter | None = None
_chain_lookup_latency: metrics.Histogram | None = None
_chain_feedback_counter: metrics.Counter | None = None
_chain_evidence_modified_counter: metrics.Counter | None = None

# In setup_metrics() after existing instruments (around line 93)
global _chain_lookup_counter, _chain_lookup_latency, _chain_feedback_counter

_chain_lookup_counter = _meter.create_counter(
    name="reasoning.chain.lookup",
    description="Reasoning chain lookup attempts",
    unit="1",
)

_chain_lookup_latency = _meter.create_histogram(
    name="reasoning.chain.lookup.latency",
    description="Reasoning chain lookup latency",
    unit="ms",
)

_chain_feedback_counter = _meter.create_counter(
    name="reasoning.chain.feedback",
    description="Reasoning chain usefulness feedback",
    unit="1",
)

_chain_evidence_modified_counter = _meter.create_counter(
    name="reasoning.chain.evidence_modified_post_creation",
    description="Chains returned where evidence was modified after chain creation",
    unit="1",
)

# After existing recording functions (around line 143)
def record_chain_lookup(
    hit: bool,
    layer_reached: int,
    similarity_score: float | None,
    cold_start: bool,
    latency_ms: float,
) -> None:
    """Record reasoning chain lookup attempt."""
    if _chain_lookup_counter is None:
        return
    _chain_lookup_counter.add(
        1,
        {
            "hit": str(hit).lower(),
            "layer": str(layer_reached),
            "cold_start": str(cold_start).lower(),
        },
    )
    if _chain_lookup_latency is not None:
        _chain_lookup_latency.record(
            latency_ms,
            {"hit": str(hit).lower(), "cold_start": str(cold_start).lower()},
        )


def record_chain_feedback(signal: str) -> None:
    """Record reasoning chain usefulness feedback."""
    if _chain_feedback_counter is None:
        return
    _chain_feedback_counter.add(1, {"signal": signal})


def record_chain_evidence_modified() -> None:
    """Record when a returned chain has evidence modified after creation."""
    if _chain_evidence_modified_counter is None:
        return
    _chain_evidence_modified_counter.add(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/telemetry/test_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/metrics.py tests/telemetry/test_metrics.py
git commit -m "feat: add reasoning chain lookup and feedback metrics"
```

---

## Task 7: Implement find_applicable_chain

**Files:**
- Create: `src/context_service/engine/chain_applicability.py`
- Test: `tests/engine/test_chain_applicability.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/engine/test_chain_applicability.py
"""Tests for reasoning chain applicability matching."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from context_service.engine.chain_applicability import find_applicable_chain


@pytest.fixture
def mock_config():
    """Mock config with test thresholds."""
    config = AsyncMock()
    config.reasoning_chain_matching.query_threshold_cold = 0.95
    config.reasoning_chain_matching.query_threshold_warm = 0.88
    config.reasoning_chain_matching.step_threshold = 0.85
    config.reasoning_chain_matching.top_k_candidates = 5
    return config


@pytest.mark.asyncio
async def test_find_applicable_chain_no_candidates(mock_config) -> None:
    """Returns None when no candidates found."""
    with patch("context_service.engine.chain_applicability.get_config", return_value=mock_config):
        with patch("context_service.engine.chain_applicability.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            with patch("context_service.engine.chain_applicability.qdrant_search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = []
                
                result = await find_applicable_chain(
                    query="test query",
                    silo_id=str(uuid4()),
                    session_id=str(uuid4()),
                )
                
                assert result is None


@pytest.mark.asyncio
async def test_find_applicable_chain_cold_start_uses_strict_threshold(mock_config) -> None:
    """Cold start (no step hints) uses stricter threshold."""
    with patch("context_service.engine.chain_applicability.get_config", return_value=mock_config):
        with patch("context_service.engine.chain_applicability.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            with patch("context_service.engine.chain_applicability.get_session_step_embeddings", new_callable=AsyncMock) as mock_steps:
                mock_steps.return_value = []  # cold start
                with patch("context_service.engine.chain_applicability.qdrant_search", new_callable=AsyncMock) as mock_search:
                    mock_search.return_value = []
                    
                    await find_applicable_chain(
                        query="test query",
                        silo_id=str(uuid4()),
                        session_id=str(uuid4()),
                    )
                    
                    # Verify cold start threshold was used
                    call_args = mock_search.call_args
                    assert call_args.kwargs["threshold"] == 0.95


@pytest.mark.asyncio
async def test_find_applicable_chain_warm_start_uses_relaxed_threshold(mock_config) -> None:
    """Warm start (has step hints) uses relaxed threshold."""
    with patch("context_service.engine.chain_applicability.get_config", return_value=mock_config):
        with patch("context_service.engine.chain_applicability.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            with patch("context_service.engine.chain_applicability.get_session_step_embeddings", new_callable=AsyncMock) as mock_steps:
                mock_steps.return_value = [[0.1] * 768]  # has step hints
                with patch("context_service.engine.chain_applicability.qdrant_search", new_callable=AsyncMock) as mock_search:
                    mock_search.return_value = []
                    
                    await find_applicable_chain(
                        query="test query",
                        silo_id=str(uuid4()),
                        session_id=str(uuid4()),
                    )
                    
                    call_args = mock_search.call_args
                    assert call_args.kwargs["threshold"] == 0.88


@pytest.mark.asyncio
async def test_find_applicable_chain_cold_start_skips_dtw(mock_config) -> None:
    """Cold start skips Layer 2 (DTW) entirely."""
    with patch("context_service.engine.chain_applicability.get_config", return_value=mock_config):
        with patch("context_service.engine.chain_applicability.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            with patch("context_service.engine.chain_applicability.get_session_step_embeddings", new_callable=AsyncMock) as mock_steps:
                mock_steps.return_value = []  # cold start
                with patch("context_service.engine.chain_applicability.qdrant_search", new_callable=AsyncMock) as mock_search:
                    mock_search.return_value = [
                        {"id": str(uuid4()), "score": 0.96, "payload": {"evidence_used": [], "step_embeddings": [[0.1] * 768]}}
                    ]
                    with patch("context_service.engine.chain_applicability.get_accessible_nodes", new_callable=AsyncMock) as mock_access:
                        mock_access.return_value = set()
                        with patch("context_service.engine.chain_applicability.dtw_similarity") as mock_dtw:
                            with patch("context_service.engine.chain_applicability.log_chain_delivery", new_callable=AsyncMock):
                                with patch("context_service.engine.chain_applicability.check_evidence_modified_after", new_callable=AsyncMock, return_value=False):
                                    
                                    await find_applicable_chain(
                                        query="test query",
                                        silo_id=str(uuid4()),
                                        session_id=str(uuid4()),
                                    )
                                    
                                    # DTW should NOT be called on cold start
                                    mock_dtw.assert_not_called()


@pytest.fixture
def mock_config_with_latency():
    """Mock config with low latency thresholds for testing."""
    config = AsyncMock()
    config.reasoning_chain_matching.query_threshold_cold = 0.95
    config.reasoning_chain_matching.query_threshold_warm = 0.88
    config.reasoning_chain_matching.step_threshold = 0.85
    config.reasoning_chain_matching.top_k_candidates = 5
    config.reasoning_chain_matching.dtw_latency_warn_ms = 10
    config.reasoning_chain_matching.dtw_latency_abort_ms = 20
    return config


@pytest.mark.asyncio
async def test_find_applicable_chain_dtw_latency_abort(mock_config_with_latency) -> None:
    """Aborts checking candidates when cumulative DTW latency exceeds threshold."""
    import time
    
    def slow_dtw(*args):
        time.sleep(0.015)  # 15ms per call
        return 0.5  # Below threshold, would normally continue
    
    with patch("context_service.engine.chain_applicability.get_config", return_value=mock_config_with_latency):
        with patch("context_service.engine.chain_applicability.embed", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = [0.1] * 768
            with patch("context_service.engine.chain_applicability.get_session_step_embeddings", new_callable=AsyncMock) as mock_steps:
                mock_steps.return_value = [[0.1] * 768]  # warm start
                with patch("context_service.engine.chain_applicability.qdrant_search", new_callable=AsyncMock) as mock_search:
                    # 5 candidates - should abort after 2 (30ms > 20ms threshold)
                    mock_search.return_value = [
                        {"id": str(uuid4()), "score": 0.9, "payload": {"evidence_used": [], "step_embeddings": [[0.1] * 768]}}
                        for _ in range(5)
                    ]
                    with patch("context_service.engine.chain_applicability.get_accessible_nodes", new_callable=AsyncMock) as mock_access:
                        mock_access.return_value = set()
                        with patch("context_service.engine.chain_applicability.dtw_similarity", side_effect=slow_dtw) as mock_dtw:
                            
                            result = await find_applicable_chain(
                                query="test query",
                                silo_id=str(uuid4()),
                                session_id=str(uuid4()),
                            )
                            
                            # Should have aborted before checking all 5
                            assert mock_dtw.call_count < 5
                            assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_chain_applicability.py -v`
Expected: FAIL with "cannot import name 'find_applicable_chain'"

- [ ] **Step 3: Implement find_applicable_chain**

```python
# src/context_service/engine/chain_applicability.py
"""Reasoning chain applicability matching."""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

import structlog

from context_service.config import get_config
from context_service.engine.dtw import dtw_similarity
from context_service.telemetry.metrics import record_chain_lookup, record_chain_evidence_modified

log = structlog.get_logger()


async def embed(text: str) -> list[float]:
    """Embed text using the configured embedding model."""
    from context_service.llm.embeddings import get_embeddings_service
    
    svc = get_embeddings_service()
    return await svc.embed(text)


async def qdrant_search(
    query_embedding: list[float],
    top_k: int,
    threshold: float,
    silo_id: str,
) -> list[dict[str, Any]]:
    """Search Qdrant for similar chains."""
    from context_service.stores.qdrant import get_qdrant_client
    
    client = get_qdrant_client()
    results = await client.search(
        collection_name="reasoning_chains",
        query_vector=query_embedding,
        limit=top_k,
        score_threshold=threshold,
        query_filter={"must": [{"key": "silo_id", "match": {"value": silo_id}}]},
    )
    return [{"id": r.id, "score": r.score, "payload": r.payload} for r in results]


async def get_session_step_embeddings(session_id: str) -> list[list[float]]:
    """Get pre-computed step embeddings for a session's in-progress reasoning."""
    from context_service.engine.sessions import get_session_steps
    
    steps = await get_session_steps(session_id)
    return [s.get("embedding", []) for s in steps if s.get("embedding")]


async def get_accessible_nodes(silo_id: str, session_id: str) -> set[str]:
    """Get node IDs accessible to this session context."""
    from context_service.engine.sessions import get_session_accessible_evidence
    
    return await get_session_accessible_evidence(silo_id, session_id)


async def log_chain_delivery(
    session_id: str,
    chain_id: str,
    query: str,
    similarity_score: float | None,
) -> None:
    """Log chain delivery for feedback tracking."""
    from context_service.db.postgres import get_async_session
    from context_service.models.postgres.chain_feedback import ChainDelivery
    
    async with get_async_session() as session:
        delivery = ChainDelivery(
            session_id=UUID(session_id),
            chain_id=UUID(chain_id),
            query=query,
            similarity_score=similarity_score,
        )
        session.add(delivery)
        await session.commit()


async def find_applicable_chain(
    query: str,
    silo_id: str,
    session_id: str,
) -> dict[str, Any] | None:
    """Find an applicable cached reasoning chain for the given query.
    
    Three-layer matching:
    1. Query intent similarity (Qdrant ANN)
    2. Step-level DTW similarity (if step hints available)
    3. Evidence accessibility check
    
    Args:
        query: The query to find a chain for.
        silo_id: Tenant isolation ID.
        session_id: Current session ID for step hints and accessibility.
        
    Returns:
        Matching chain dict or None if no applicable chain found.
    """
    start_time = time.perf_counter()
    config = get_config().reasoning_chain_matching
    
    step_hints = await get_session_step_embeddings(session_id)
    is_cold_start = len(step_hints) == 0
    
    query_embedding = await embed(query)
    threshold = config.query_threshold_cold if is_cold_start else config.query_threshold_warm
    
    candidates = await qdrant_search(
        query_embedding=query_embedding,
        top_k=config.top_k_candidates,
        threshold=threshold,
        silo_id=silo_id,
    )
    
    if not candidates:
        latency_ms = (time.perf_counter() - start_time) * 1000
        record_chain_lookup(
            hit=False,
            layer_reached=1,
            similarity_score=None,
            cold_start=is_cold_start,
            latency_ms=latency_ms,
        )
        return None
    
    accessible = await get_accessible_nodes(silo_id, session_id)
    
    cumulative_dtw_ms = 0.0
    
    for chain in candidates:
        if is_cold_start:
            similarity_score = None
        else:
            chain_step_embeddings = chain["payload"].get("step_embeddings", [])
            if not chain_step_embeddings:
                continue
            
            # DTW with latency guard
            dtw_start = time.perf_counter()
            similarity_score = dtw_similarity(chain_step_embeddings, step_hints)
            dtw_ms = (time.perf_counter() - dtw_start) * 1000
            cumulative_dtw_ms += dtw_ms
            
            if dtw_ms > config.dtw_latency_warn_ms:
                log.warning("dtw_latency_warning", dtw_ms=dtw_ms, chain_id=chain["id"])
            
            if cumulative_dtw_ms > config.dtw_latency_abort_ms:
                log.warning("dtw_latency_abort", cumulative_ms=cumulative_dtw_ms)
                break
            
            if similarity_score < config.step_threshold:
                continue
        
        evidence_used = set(chain["payload"].get("evidence_used", []))
        if not evidence_used.issubset(accessible):
            continue
        
        # Check for evidence modification (monitoring only, not blocking)
        chain_created_at = chain["payload"].get("created_at")
        if chain_created_at:
            evidence_modified = await check_evidence_modified_after(
                list(evidence_used), chain_created_at
            )
            if evidence_modified:
                record_chain_evidence_modified()
        
        await log_chain_delivery(session_id, chain["id"], query, similarity_score)
        
        latency_ms = (time.perf_counter() - start_time) * 1000
        record_chain_lookup(
            hit=True,
            layer_reached=3,
            similarity_score=similarity_score,
            cold_start=is_cold_start,
            latency_ms=latency_ms,
        )
        
        return chain
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    record_chain_lookup(
        hit=False,
        layer_reached=3,  # All candidates failed Layer 3 (evidence check)
        similarity_score=None,
        cold_start=is_cold_start,
        latency_ms=latency_ms,
    )
    return None


async def check_evidence_modified_after(
    evidence_ids: list[str],
    chain_created_at: str,
) -> bool:
    """Check if any evidence was modified after chain creation (monitoring only)."""
    from context_service.engine.memgraph_store import get_memgraph_store
    from datetime import datetime
    
    if not evidence_ids:
        return False
    
    store = get_memgraph_store()
    for eid in evidence_ids:
        node = await store.get_node(eid)
        if node and node.get("updated_at"):
            if node["updated_at"] > chain_created_at:
                return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_chain_applicability.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/chain_applicability.py \
        tests/engine/test_chain_applicability.py
git commit -m "feat: implement find_applicable_chain with three-layer matching"
```

---

## Task 8: Modify write path to attach query embedding

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py`
- Test: `tests/mcp/tools/test_context_store.py`

- [ ] **Step 1: Read current _context_reason implementation**

Run: `grep -n "async def _context_reason" src/context_service/mcp/tools/context_store.py`
Note the line number for modification.

- [ ] **Step 2: Write the failing test**

```python
# Add to tests/mcp/tools/test_context_store.py

@pytest.mark.asyncio
async def test_context_reason_attaches_query_embedding(
    mcp_context: MockMCPContext,
) -> None:
    """context_reason stores query_embedding on chain creation."""
    with patch("context_service.mcp.tools.context_store.embed", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = [0.1] * 768
        
        result = await context_store(
            layer="intelligence",
            subtype="reason",
            steps=[{"step": 1, "reasoning": "test reasoning"}],
            conclusion="test conclusion",
        )
        
        assert "error" not in result
        mock_embed.assert_called_once()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_context_store.py::test_context_reason_attaches_query_embedding -v`
Expected: FAIL (embed not called)

- [ ] **Step 4: Add query parameter to _context_reason signature**

First, update the function signature to accept an optional query parameter:

```python
async def _context_reason(
    silo_id: str | None,
    steps: list[dict[str, Any]],
    conclusion: str | None = None,
    evidence_used: list[str] | None = None,
    crystallizations: list[dict[str, Any]] | None = None,
    session_id: str | None = None,
    parent_chain_id: str | None = None,
    query: str | None = None,  # NEW: originating query for embedding
) -> dict[str, Any]:
```

- [ ] **Step 5: Attach query embedding after chain creation**

In `src/context_service/mcp/tools/context_store.py`, after chain node creation, add:

```python
# After: chain_node = await create_chain_node(...)
# Add embedding attachment:
from context_service.llm.embeddings import get_embeddings_service

# Use explicit query if provided, else fall back to conclusion
query_text = query or conclusion
if query_text:
    embeddings_svc = get_embeddings_service()
    query_embedding = await embeddings_svc.embed(query_text)

    await ctx_svc.attach_chain_embedding(
        chain_id=chain_node.id,
        embedding_type="query",
        embedding=query_embedding,
    )

# Schedule async step embeddings
for step in parsed_steps:
    await schedule_step_embedding(chain_node.id, step.step, step.reasoning)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_context_store.py::test_context_reason_attaches_query_embedding -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py \
        tests/mcp/tools/test_context_store.py
git commit -m "feat: attach query embedding at chain creation time"
```

---

## Task 9: Create Dagster feedback job

**Files:**
- Create: `src/context_service/pipelines/assets/chain_feedback.py`
- Test: `tests/pipelines/assets/test_chain_feedback.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/assets/test_chain_feedback.py
"""Tests for chain feedback Dagster asset."""

from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from context_service.pipelines.assets.chain_feedback import compute_chain_usefulness


@pytest.mark.asyncio
async def test_compute_chain_usefulness_useful_signal() -> None:
    """Chain is marked useful when subsequent steps overlap."""
    chain_id = str(uuid4())
    delivery = {
        "session_id": str(uuid4()),
        "chain_id": chain_id,
        "query": "test query",
        "delivered_at": datetime.now(UTC) - timedelta(minutes=10),
    }
    chain_steps = [[0.1] * 768, [0.2] * 768]
    subsequent_steps = [[0.1] * 768, [0.2] * 768]  # Same steps
    
    with patch("context_service.pipelines.assets.chain_feedback.get_session_steps_after", new_callable=AsyncMock) as mock_get_session:
        mock_get_session.return_value = subsequent_steps
        with patch("context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings", new_callable=AsyncMock) as mock_get_chain:
            mock_get_chain.return_value = chain_steps
            with patch("context_service.pipelines.assets.chain_feedback.store_feedback", new_callable=AsyncMock) as mock_store:
                
                await compute_chain_usefulness(delivery)
                
                mock_get_chain.assert_called_once_with(chain_id)
                mock_store.assert_called_once()
                call_args = mock_store.call_args
                assert call_args.kwargs["signal"] == "useful"


@pytest.mark.asyncio
async def test_compute_chain_usefulness_not_useful_new_chain() -> None:
    """Chain is marked not_useful when agent creates new chain for similar query."""
    chain_id = str(uuid4())
    delivery = {
        "session_id": str(uuid4()),
        "chain_id": chain_id,
        "query": "test query",
        "delivered_at": datetime.now(UTC) - timedelta(minutes=10),
    }
    chain_steps = [[0.1] * 768]
    
    with patch("context_service.pipelines.assets.chain_feedback.get_session_steps_after", new_callable=AsyncMock) as mock_get_session:
        mock_get_session.return_value = [[0.9] * 768]  # Different steps
        with patch("context_service.pipelines.assets.chain_feedback.get_chain_step_embeddings", new_callable=AsyncMock) as mock_get_chain:
            mock_get_chain.return_value = chain_steps
            with patch("context_service.pipelines.assets.chain_feedback.check_new_chain_created", new_callable=AsyncMock) as mock_check:
                mock_check.return_value = True  # New chain was created
                with patch("context_service.pipelines.assets.chain_feedback.store_feedback", new_callable=AsyncMock) as mock_store:
                    
                    await compute_chain_usefulness(delivery)
                    
                    mock_store.assert_called_once()
                    call_args = mock_store.call_args
                    assert call_args.kwargs["signal"] == "not_useful"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/assets/test_chain_feedback.py -v`
Expected: FAIL with "cannot import name 'compute_chain_usefulness'"

- [ ] **Step 3: Implement Dagster asset**

```python
# src/context_service/pipelines/assets/chain_feedback.py
"""Dagster assets for reasoning chain feedback tracking."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC

from dagster import asset, AssetExecutionContext

from context_service.config import get_config
from context_service.engine.dtw import dtw_similarity
from context_service.telemetry.metrics import record_chain_feedback


async def get_recent_deliveries(hours: int = 1) -> list[dict]:
    """Get chain deliveries from the last N hours."""
    from sqlalchemy import select
    from context_service.db.postgres import get_async_session
    from context_service.models.postgres.chain_feedback import ChainDelivery
    
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    
    async with get_async_session() as session:
        result = await session.execute(
            select(ChainDelivery).where(ChainDelivery.delivered_at > cutoff)
        )
        rows = result.scalars().all()
        return [
            {
                "session_id": str(r.session_id),
                "chain_id": str(r.chain_id),
                "query": r.query,
                "delivered_at": r.delivered_at,
            }
            for r in rows
        ]


async def get_session_steps_after(
    session_id: str,
    after: datetime,
    limit: int = 10,
) -> list[list[float]]:
    """Get step embeddings created in session after a timestamp."""
    from context_service.engine.sessions import get_session_steps
    
    steps = await get_session_steps(session_id, after=after, limit=limit)
    return [s.get("embedding", []) for s in steps if s.get("embedding")]


async def get_chain_step_embeddings(chain_id: str) -> list[list[float]]:
    """Get step embeddings for a chain."""
    from context_service.engine.memgraph_store import get_memgraph_store
    
    store = get_memgraph_store()
    chain = await store.get_chain(chain_id)
    return chain.get("step_embeddings", []) if chain else []


async def check_new_chain_created(
    session_id: str,
    after: datetime,
    query: str,
) -> bool:
    """Check if a new chain was created in session for similar query."""
    from context_service.engine.sessions import get_session_chains
    from context_service.llm.embeddings import get_embeddings_service
    
    chains = await get_session_chains(session_id, after=after)
    if not chains:
        return False
    
    embeddings_svc = get_embeddings_service()
    query_emb = await embeddings_svc.embed(query)
    
    for chain in chains:
        chain_query_emb = chain.get("query_embedding", [])
        if chain_query_emb:
            from numpy import dot
            from numpy.linalg import norm
            similarity = dot(query_emb, chain_query_emb) / (norm(query_emb) * norm(chain_query_emb))
            if similarity > 0.85:
                return True
    
    return False


async def store_feedback(chain_id: str, signal: str) -> None:
    """Store feedback signal for a chain."""
    from context_service.db.postgres import get_async_session
    from context_service.models.postgres.chain_feedback import ChainFeedback
    from uuid import UUID
    
    async with get_async_session() as session:
        feedback = ChainFeedback(chain_id=UUID(chain_id), signal=signal)
        session.add(feedback)
        await session.commit()
    
    record_chain_feedback(signal)


async def compute_chain_usefulness(delivery: dict) -> None:
    """Compute usefulness signal for a single delivery."""
    config = get_config().chain_feedback
    
    subsequent_steps = await get_session_steps_after(
        session_id=delivery["session_id"],
        after=delivery["delivered_at"],
        limit=config.min_subsequent_steps + 5,
    )
    
    if len(subsequent_steps) < config.min_subsequent_steps:
        return
    
    chain_steps = await get_chain_step_embeddings(delivery["chain_id"])
    if not chain_steps:
        return
    
    overlap = dtw_similarity(chain_steps, subsequent_steps)
    
    if overlap > 0.7:
        signal = "useful"
    elif await check_new_chain_created(
        delivery["session_id"],
        delivery["delivered_at"],
        delivery["query"],
    ):
        signal = "not_useful"
    else:
        signal = "unclear"
    
    await store_feedback(delivery["chain_id"], signal=signal)


@asset(
    description="Computes usefulness signals for delivered reasoning chains",
    group_name="chain_feedback",
)
def chain_usefulness_signals(context: AssetExecutionContext) -> None:
    """Analyze recent chain deliveries and compute usefulness signals."""
    import asyncio
    
    async def run():
        deliveries = await get_recent_deliveries(hours=1)
        context.log.info(f"Processing {len(deliveries)} chain deliveries")
        
        for delivery in deliveries:
            try:
                await compute_chain_usefulness(delivery)
            except Exception as e:
                context.log.warning(f"Failed to process delivery {delivery['chain_id']}: {e}")
    
    asyncio.run(run())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/assets/test_chain_feedback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/pipelines/assets/chain_feedback.py \
        tests/pipelines/assets/test_chain_feedback.py
git commit -m "feat: add Dagster asset for chain usefulness feedback"
```

---

## Task 10: Integration test

**Files:**
- Create: `tests/integration/test_chain_applicability.py`

- [ ] **Step 1: Write integration test**

```python
# tests/integration/test_chain_applicability.py
"""Integration tests for reasoning chain applicability matching."""

from uuid import uuid4

import pytest

from context_service.engine.chain_applicability import find_applicable_chain


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_applicable_chain_end_to_end(
    integration_context,
) -> None:
    """Full flow: create chain, then find it via applicability matching."""
    silo_id = str(uuid4())
    session_id = str(uuid4())
    
    # Create a chain via context_store
    from context_service.mcp.tools.context_store import context_store
    
    result = await context_store(
        layer="intelligence",
        subtype="reason",
        steps=[
            {"step": 1, "reasoning": "First we check the database connection"},
            {"step": 2, "reasoning": "Then we analyze query performance"},
        ],
        conclusion="Database queries are slow due to missing index",
        silo_id=silo_id,
        session_id=session_id,
    )
    
    assert "error" not in result
    chain_id = result["chain_id"]
    
    # Wait for async embedding to complete
    import asyncio
    await asyncio.sleep(0.5)
    
    # Now search for applicable chain
    found = await find_applicable_chain(
        query="Why is the database slow?",
        silo_id=silo_id,
        session_id=session_id,
    )
    
    # Should find our chain (cold start, but similar query)
    assert found is not None
    assert found["id"] == chain_id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_applicable_chain_cross_silo_isolation(
    integration_context,
) -> None:
    """Chains from other silos are not returned."""
    silo_a = str(uuid4())
    silo_b = str(uuid4())
    session_id = str(uuid4())
    
    from context_service.mcp.tools.context_store import context_store
    
    # Create chain in silo A
    await context_store(
        layer="intelligence",
        subtype="reason",
        steps=[{"step": 1, "reasoning": "Test reasoning"}],
        conclusion="Test conclusion",
        silo_id=silo_a,
        session_id=session_id,
    )
    
    import asyncio
    await asyncio.sleep(0.5)
    
    # Search in silo B
    found = await find_applicable_chain(
        query="Test conclusion",
        silo_id=silo_b,
        session_id=session_id,
    )
    
    # Should NOT find chain from silo A
    assert found is None
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/integration/test_chain_applicability.py -v --run-integration`
Expected: PASS (requires docker stack running)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_chain_applicability.py
git commit -m "test: add integration tests for chain applicability matching"
```

---

## Task 11: Update conversation log and finalize

**Files:**
- Update: `/home/novusedge/claude-bits/engrammic/2026-05-11-reasoning-chain-equivalence.md`

- [ ] **Step 1: Run full test suite**

Run: `uv run just check && uv run just test`
Expected: All checks pass

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "feat: complete reasoning chain applicability matching implementation"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Add dtaidistance dependency | pyproject.toml |
| 2 | Add configuration file | config/reasoning_chain.yaml |
| 3 | Postgres models for feedback | models/postgres/chain_feedback.py |
| 4 | Alembic migration | alembic/versions/ |
| 5 | DTW wrapper | engine/dtw.py |
| 6 | Retrieval metrics | telemetry/metrics.py |
| 7 | find_applicable_chain | engine/chain_applicability.py |
| 8 | Write path embedding | mcp/tools/context_store.py |
| 9 | Dagster feedback job | pipelines/assets/chain_feedback.py |
| 10 | Integration test | tests/integration/ |
| 11 | Finalize | - |

Estimated time: 4-5 hours
