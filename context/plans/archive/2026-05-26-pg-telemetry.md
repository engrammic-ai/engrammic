# PostgreSQL Telemetry Consolidation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SigNoz/OTEL with PostgreSQL-based telemetry. All metrics flow to PG tables, dashboards via Metabase.

**Architecture:** In-process MetricsBuffer aggregates metrics per minute, background task flushes to `service_metrics` table. Errors logged individually to `service_errors`. Dagster job snapshots storage gauges hourly. Pruning job enforces retention. Existing `metrics.py` becomes a re-export shim so all existing imports continue to work.

**Tech Stack:** PostgreSQL, asyncpg, Dagster, Metabase

**Spec:** `context/brainstorm/2026-05-26-service-metrics-schema.md`

---

## File Structure

### Database
- Create: `alembic/versions/0014_create_service_telemetry_tables.py`

### Telemetry Module
- Create: `src/context_service/telemetry/buffer.py` - MetricsBuffer class
- Create: `src/context_service/telemetry/flush.py` - Background flush task
- Create: `src/context_service/telemetry/recorder.py` - New PG-based implementations
- Modify: `src/context_service/telemetry/metrics.py` - Convert to re-export shim (keeps all imports working)
- Modify: `src/context_service/telemetry/tracing.py` - Replace with no-op stubs
- Modify: `src/context_service/telemetry/__init__.py` - Update exports

### Dagster
- Create: `src/context_service/pipelines/jobs/telemetry_gauges.py` - Hourly storage snapshots
- Create: `src/context_service/pipelines/jobs/telemetry_prune.py` - Retention pruning
- Modify: `src/context_service/pipelines/resources.py` - Add PostgresResource
- Modify: `src/context_service/pipelines/definitions.py` - Register new jobs
- Modify: `src/context_service/pipelines/schedules.py` - Add schedules

### Application Wiring
- Modify: `src/context_service/api/app.py` - Add flush task, remove OTEL setup

### Infrastructure Removal
- Delete: `infra/components/signoz.py`
- Modify: `infra/components/__init__.py` - Remove SignozHost export
- Modify: `infra/__main__.py` - Remove SignozHost, OTEL env vars

### Dependencies
- Modify: `pyproject.toml` - Remove OTEL packages

---

## Task 1: Create Telemetry Tables Migration

**Files:**
- Create: `alembic/versions/0014_create_service_telemetry_tables.py`

- [ ] **Step 1: Create migration file**

```python
"""create service telemetry tables

Revision ID: 0014
Revises: 0013_seed_hosted_beacon_secret
Create Date: 2026-05-27

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str = "0013_seed_hosted_beacon_secret"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_metrics",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("metric_name", sa.String(100), nullable=False),
        sa.Column("count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("latency_sum_ms", sa.Float, nullable=False, server_default="0"),
        sa.Column("latency_p50_ms", sa.Float, nullable=True),
        sa.Column("latency_p95_ms", sa.Float, nullable=True),
        sa.Column("latency_max_ms", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket", "silo_id", "metric_name"),
    )
    op.create_index("idx_service_metrics_bucket", "service_metrics", ["bucket"])
    op.create_index("idx_service_metrics_silo_bucket", "service_metrics", ["silo_id", "bucket"])
    op.create_index("idx_service_metrics_metric_bucket", "service_metrics", ["metric_name", "bucket"])

    op.create_table(
        "service_errors",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("error_type", sa.String(200), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("tool_name", sa.String(100), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now() + INTERVAL '30 days'"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_service_errors_occurred", "service_errors", ["occurred_at"])
    op.create_index("idx_service_errors_silo", "service_errors", ["silo_id", "occurred_at"])
    op.create_index("idx_service_errors_type", "service_errors", ["error_type", "occurred_at"])
    op.create_index("idx_service_errors_expires", "service_errors", ["expires_at"])

    op.create_table(
        "service_gauges",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "measured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("silo_id", sa.String(255), nullable=False),
        sa.Column("node_count_memory", sa.Integer, nullable=True),
        sa.Column("node_count_knowledge", sa.Integer, nullable=True),
        sa.Column("node_count_wisdom", sa.Integer, nullable=True),
        sa.Column("edge_count", sa.Integer, nullable=True),
        sa.Column("qdrant_point_count", sa.Integer, nullable=True),
        sa.Column("qdrant_collection_size_bytes", sa.BigInteger, nullable=True),
        sa.Column("memgraph_vertex_count", sa.Integer, nullable=True),
        sa.Column("memgraph_edge_count", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("measured_at", "silo_id"),
    )
    op.create_index("idx_service_gauges_silo_time", "service_gauges", ["silo_id", "measured_at"])


def downgrade() -> None:
    op.drop_index("idx_service_gauges_silo_time", table_name="service_gauges")
    op.drop_table("service_gauges")

    op.drop_index("idx_service_errors_expires", table_name="service_errors")
    op.drop_index("idx_service_errors_type", table_name="service_errors")
    op.drop_index("idx_service_errors_silo", table_name="service_errors")
    op.drop_index("idx_service_errors_occurred", table_name="service_errors")
    op.drop_table("service_errors")

    op.drop_index("idx_service_metrics_metric_bucket", table_name="service_metrics")
    op.drop_index("idx_service_metrics_silo_bucket", table_name="service_metrics")
    op.drop_index("idx_service_metrics_bucket", table_name="service_metrics")
    op.drop_table("service_metrics")
```

- [ ] **Step 2: Verify migration syntax**

Run: `uv run alembic check`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/0014_create_service_telemetry_tables.py
git commit -m "feat(db): add service telemetry tables migration"
```

---

## Task 2: Implement MetricsBuffer

**Files:**
- Create: `src/context_service/telemetry/buffer.py`
- Create: `tests/unit/telemetry/test_buffer.py`

- [ ] **Step 1: Write tests for MetricsBuffer**

```python
# tests/unit/telemetry/test_buffer.py
"""Tests for MetricsBuffer."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from context_service.telemetry.buffer import MetricsBuffer


class TestMetricsBuffer:
    def test_record_increments_count(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        assert len(rows) == 1
        assert rows[0]["count"] == 2
        assert rows[0]["error_count"] == 0

    def test_record_tracks_errors(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1", error=True)
        buffer.record("tool.remember", "silo-1", error=False)

        rows = buffer.flush()
        assert rows[0]["count"] == 2
        assert rows[0]["error_count"] == 1

    def test_record_aggregates_latency(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.recall", "silo-1", latency_ms=100.0)
        buffer.record("tool.recall", "silo-1", latency_ms=200.0)
        buffer.record("tool.recall", "silo-1", latency_ms=300.0)

        rows = buffer.flush()
        assert rows[0]["latency_sum_ms"] == 600.0
        assert rows[0]["latency_p50_ms"] == 200.0
        assert rows[0]["latency_max_ms"] == 300.0

    def test_separate_buckets_per_silo(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.remember", "silo-2")

        rows = buffer.flush()
        assert len(rows) == 2
        silo_ids = {r["silo_id"] for r in rows}
        assert silo_ids == {"silo-1", "silo-2"}

    def test_separate_buckets_per_metric(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")
        buffer.record("tool.recall", "silo-1")

        rows = buffer.flush()
        assert len(rows) == 2
        metrics = {r["metric_name"] for r in rows}
        assert metrics == {"tool.remember", "tool.recall"}

    def test_flush_clears_buffer(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows1 = buffer.flush()
        rows2 = buffer.flush()

        assert len(rows1) == 1
        assert len(rows2) == 0

    def test_percentile_empty_list(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        assert rows[0]["latency_p50_ms"] is None
        assert rows[0]["latency_p95_ms"] is None
        assert rows[0]["latency_max_ms"] is None

    def test_bucket_is_truncated_to_minute(self) -> None:
        buffer = MetricsBuffer()
        buffer.record("tool.remember", "silo-1")

        rows = buffer.flush()
        bucket: datetime = rows[0]["bucket"]
        assert bucket.second == 0
        assert bucket.microsecond == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/telemetry/test_buffer.py -v`

Expected: FAIL with "No module named 'context_service.telemetry.buffer'"

- [ ] **Step 3: Implement MetricsBuffer**

```python
# src/context_service/telemetry/buffer.py
"""In-process metrics buffer for aggregation before DB flush."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MetricBucket:
    """Aggregated metrics for a single (time, silo, metric) key."""

    count: int = 0
    error_count: int = 0
    latencies: list[float] = field(default_factory=list)


class MetricsBuffer:
    """Thread-safe buffer for metric aggregation.

    Records are keyed by (bucket_time, silo_id, metric_name).
    Call flush() periodically to get aggregated rows and clear the buffer.
    """

    def __init__(self) -> None:
        self._buckets: dict[tuple[str, str, str], MetricBucket] = defaultdict(MetricBucket)
        self._lock = threading.Lock()

    def record(
        self,
        metric_name: str,
        silo_id: str,
        latency_ms: float | None = None,
        error: bool = False,
    ) -> None:
        """Record a metric observation."""
        bucket_time = self._truncate_to_minute(time.time())
        key = (bucket_time, silo_id, metric_name)

        with self._lock:
            bucket = self._buckets[key]
            bucket.count += 1
            if error:
                bucket.error_count += 1
            if latency_ms is not None:
                bucket.latencies.append(latency_ms)

    def flush(self) -> list[dict[str, Any]]:
        """Return aggregated metrics and clear buffer."""
        with self._lock:
            results: list[dict[str, Any]] = []
            for (bucket_time, silo_id, metric_name), bucket in self._buckets.items():
                latencies = sorted(bucket.latencies) if bucket.latencies else []
                results.append(
                    {
                        "bucket": datetime.fromisoformat(bucket_time),
                        "silo_id": silo_id,
                        "metric_name": metric_name,
                        "count": bucket.count,
                        "error_count": bucket.error_count,
                        "latency_sum_ms": sum(latencies),
                        "latency_p50_ms": self._percentile(latencies, 50),
                        "latency_p95_ms": self._percentile(latencies, 95),
                        "latency_max_ms": max(latencies) if latencies else None,
                    }
                )
            self._buckets.clear()
            return results

    def _truncate_to_minute(self, ts: float) -> str:
        """Truncate timestamp to minute boundary, return ISO string."""
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        truncated = dt.replace(second=0, microsecond=0)
        return truncated.isoformat()

    def _percentile(self, sorted_values: list[float], p: int) -> float | None:
        """Compute percentile from sorted list."""
        if not sorted_values:
            return None
        k = (len(sorted_values) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_values) else f
        return sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f])
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/telemetry/test_buffer.py -v`

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/buffer.py tests/unit/telemetry/test_buffer.py
git commit -m "feat(telemetry): add MetricsBuffer for in-process aggregation"
```

---

## Task 3: Implement Flush Task

**Files:**
- Create: `src/context_service/telemetry/flush.py`
- Create: `tests/unit/telemetry/test_flush.py`

- [ ] **Step 1: Write tests for flush_metrics_to_db**

```python
# tests/unit/telemetry/test_flush.py
"""Tests for metrics flush to database."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from context_service.telemetry.buffer import MetricsBuffer
from context_service.telemetry.flush import flush_metrics_to_db


@pytest.mark.asyncio
async def test_flush_empty_buffer_does_nothing() -> None:
    buffer = MetricsBuffer()
    pool = AsyncMock()

    await flush_metrics_to_db(pool, buffer)

    pool.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_flush_executes_insert() -> None:
    buffer = MetricsBuffer()
    buffer.record("tool.remember", "silo-1", latency_ms=100.0)

    conn = AsyncMock()
    pool = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn

    await flush_metrics_to_db(pool, buffer)

    conn.executemany.assert_called_once()
    call_args = conn.executemany.call_args
    assert "INSERT INTO service_metrics" in call_args[0][0]
    assert len(call_args[0][1]) == 1


@pytest.mark.asyncio
async def test_flush_clears_buffer_after_insert() -> None:
    buffer = MetricsBuffer()
    buffer.record("tool.remember", "silo-1")

    conn = AsyncMock()
    pool = AsyncMock()
    pool.acquire.return_value.__aenter__.return_value = conn

    await flush_metrics_to_db(pool, buffer)

    assert buffer.flush() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/telemetry/test_flush.py -v`

Expected: FAIL with "No module named 'context_service.telemetry.flush'"

- [ ] **Step 3: Implement flush.py**

```python
# src/context_service/telemetry/flush.py
"""Background task to flush metrics buffer to PostgreSQL."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    import asyncpg

    from context_service.telemetry.buffer import MetricsBuffer

logger = structlog.get_logger(__name__)


async def flush_metrics_to_db(pool: asyncpg.Pool, buffer: MetricsBuffer) -> None:
    """Flush buffered metrics to service_metrics table."""
    rows = buffer.flush()
    if not rows:
        return

    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO service_metrics (
                bucket, silo_id, metric_name, count, error_count,
                latency_sum_ms, latency_p50_ms, latency_p95_ms, latency_max_ms
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (bucket, silo_id, metric_name) DO UPDATE SET
                count = service_metrics.count + EXCLUDED.count,
                error_count = service_metrics.error_count + EXCLUDED.error_count,
                latency_sum_ms = service_metrics.latency_sum_ms + EXCLUDED.latency_sum_ms
            """,
            [
                (
                    r["bucket"],
                    r["silo_id"],
                    r["metric_name"],
                    r["count"],
                    r["error_count"],
                    r["latency_sum_ms"],
                    r["latency_p50_ms"],
                    r["latency_p95_ms"],
                    r["latency_max_ms"],
                )
                for r in rows
            ],
        )

    logger.debug("metrics_flushed", row_count=len(rows))


async def record_error_to_db(
    pool: asyncpg.Pool,
    silo_id: str,
    error_type: str,
    error_message: str | None = None,
    tool_name: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Record an individual error to service_errors table."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO service_errors (silo_id, error_type, error_message, tool_name, context)
            VALUES ($1, $2, $3, $4, $5)
            """,
            silo_id,
            error_type,
            error_message,
            tool_name,
            json.dumps(context) if context else None,
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/telemetry/test_flush.py -v`

Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add src/context_service/telemetry/flush.py tests/unit/telemetry/test_flush.py
git commit -m "feat(telemetry): add flush task for metrics to PostgreSQL"
```

---

## Task 4: Implement Recorder Module

**Files:**
- Create: `src/context_service/telemetry/recorder.py`

- [ ] **Step 1: Create recorder.py with all record_* functions**

This module provides the actual implementations. The existing `metrics.py` will re-export these.

```python
# src/context_service/telemetry/recorder.py
"""PG-based telemetry recorder implementations.

All record_* functions write to an in-process MetricsBuffer.
The buffer is flushed periodically to PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from context_service.telemetry.buffer import MetricsBuffer

if TYPE_CHECKING:
    import asyncpg

_buffer: MetricsBuffer | None = None
_db_pool: asyncpg.Pool | None = None


def setup_metrics(service_name: str = "context-service") -> None:
    """Initialize telemetry. Call once at startup."""
    global _buffer
    _buffer = MetricsBuffer()


def set_db_pool(pool: asyncpg.Pool) -> None:
    """Set the database pool for flushing."""
    global _db_pool
    _db_pool = pool


def get_buffer() -> MetricsBuffer | None:
    """Get the global metrics buffer."""
    return _buffer


def get_db_pool() -> asyncpg.Pool | None:
    """Get the database pool for flushing."""
    return _db_pool


def record_request(method: str, path: str, status: int, duration_ms: float) -> None:
    """Record HTTP request metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"http.{method}.{status}",
        silo_id="system",
        latency_ms=duration_ms,
    )


@contextmanager
def track_active_request(method: str, path: str) -> Generator[None, None, None]:
    """Track active request count (no-op in PG mode)."""
    yield


def record_db_query(operation: str, duration_ms: float) -> None:
    """Record database query duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"db.{operation}",
        silo_id="system",
        latency_ms=duration_ms,
    )


def record_embedding(model: str, duration_ms: float, silo_id: str | None = None) -> None:
    """Record embedding generation duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"embedding.{model}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


def record_mcp_tool(
    tool: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record MCP tool invocation metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"tool.{tool}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
        error=not success,
    )


def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"llm.tokens.{model}.input", silo_id="system")
    _buffer.record(metric_name=f"llm.tokens.{model}.output", silo_id="system")


def record_llm_call(
    model: str,
    duration_ms: float,
    success: bool = True,
    silo_id: str | None = None,
) -> None:
    """Record LLM call duration."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"llm.{model}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
        error=not success,
    )


def record_context_recall_size(layer: str, bytes_size: int) -> None:
    """Record context recall response size."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.size.{layer}", silo_id="system")


def record_chain_lookup(
    hit: bool,
    layer_reached: int,
    similarity_score: float | None,
    cold_start: bool,
    latency_ms: float,
) -> None:
    """Record reasoning chain lookup attempt."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"chain.lookup.{'hit' if hit else 'miss'}",
        silo_id="system",
        latency_ms=latency_ms,
    )


def record_chain_feedback(signal: str) -> None:
    """Record reasoning chain usefulness feedback."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"chain.feedback.{signal}", silo_id="system")


def record_chain_evidence_modified() -> None:
    """Record when a returned chain has evidence modified after creation."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.evidence_modified", silo_id="system")


def record_reranking(latency_ms: float, success: bool) -> None:
    """Record reranking operation metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.reranking",
        silo_id="system",
        latency_ms=latency_ms,
        error=not success,
    )


def record_query_expansion(latency_ms: float, success: bool) -> None:
    """Record query expansion metrics."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.query_expansion",
        silo_id="system",
        latency_ms=latency_ms,
        error=not success,
    )


def record_hard_query_detection(is_hard: bool) -> None:
    """Record hard query detection."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"recall.hard_query.{'true' if is_hard else 'false'}",
        silo_id="system",
    )


def record_circuit_breaker_opened(store: str) -> None:
    """Record a circuit breaker trip."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"circuit_breaker.{store}.opened", silo_id="system")


def record_circuit_breaker_closed(store: str) -> None:
    """Record a circuit breaker reset."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"circuit_breaker.{store}.closed", silo_id="system")


def record_store_error(store: str, operation: str) -> None:
    """Record a store operation error."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"store.{store}.error", silo_id="system", error=True)


def record_orphan_chain_exhausted(silo_id: str) -> None:
    """Record an orphan chain that exhausted all retries."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.orphan.exhausted", silo_id=silo_id)


def record_orphan_chain_recovered(silo_id: str) -> None:
    """Record an orphan chain that was successfully recovered."""
    if _buffer is None:
        return
    _buffer.record(metric_name="chain.orphan.recovered", silo_id=silo_id)


def record_source_tier_resolved(tier: str, layer: str, silo_id: str) -> None:
    """Record a source tier resolution event."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"source_tier.{tier}.{layer}", silo_id=silo_id)


def record_embedding_cache_hit(task: str) -> None:
    """Record an embedding cache hit."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"embedding.cache.{task}.hit", silo_id="system")


def record_embedding_cache_miss(task: str) -> None:
    """Record an embedding cache miss."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"embedding.cache.{task}.miss", silo_id="system")


def record_belief_confidence(confidence: float, silo_id: str | None = None) -> None:
    """Record the confidence score of a declared belief."""
    if _buffer is None:
        return
    _buffer.record(metric_name="belief.confidence", silo_id=silo_id or "unknown")


def record_cache_hit(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache hit."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.hit", silo_id=silo_id or "unknown")


def record_cache_miss(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache miss."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.miss", silo_id=silo_id or "unknown")


def record_cache_eviction(cache_type: str, silo_id: str | None = None) -> None:
    """Record cache eviction."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"cache.{cache_type}.eviction", silo_id=silo_id or "unknown")


def record_recall_latency(
    duration_ms: float,
    depth: int,
    source: str,
    silo_id: str | None = None,
) -> None:
    """Record recall operation latency."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"recall.{source}",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


def record_recall_depth(depth: int, silo_id: str | None = None) -> None:
    """Record recall depth."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.depth.{depth}", silo_id=silo_id or "unknown")


def record_recall_result_count(count: int, layer: str, silo_id: str | None = None) -> None:
    """Record recall result count."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"recall.results.{layer}", silo_id=silo_id or "unknown")


def record_tool_error(tool_name: str, error_type: str, silo_id: str | None = None) -> None:
    """Record tool error."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name=f"tool.{tool_name}",
        silo_id=silo_id or "unknown",
        error=True,
    )


def record_supersession_used(tool_name: str, silo_id: str | None = None) -> None:
    """Record supersession usage."""
    if _buffer is None:
        return
    _buffer.record(metric_name="store.supersession_used", silo_id=silo_id or "unknown")


def record_supersession_skipped(silo_id: str | None = None) -> None:
    """Record supersession skipped."""
    if _buffer is None:
        return
    _buffer.record(metric_name="store.supersession_skipped", silo_id=silo_id or "unknown")


def record_node_confidence(confidence: float, layer: str, silo_id: str | None = None) -> None:
    """Record node confidence at write time."""
    if _buffer is None:
        return
    _buffer.record(metric_name=f"node.confidence.{layer}", silo_id=silo_id or "unknown")


def record_engagement_latency(duration_ms: float, silo_id: str | None = None) -> None:
    """Record engagement detection latency during recall."""
    if _buffer is None:
        return
    _buffer.record(
        metric_name="recall.engagement",
        silo_id=silo_id or "unknown",
        latency_ms=duration_ms,
    )


ORPHAN_CHAINS_EXHAUSTED = record_orphan_chain_exhausted
ORPHAN_CHAINS_RECOVERED = record_orphan_chain_recovered
```

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/context_service/telemetry/recorder.py`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/telemetry/recorder.py
git commit -m "feat(telemetry): add PG-based recorder implementations"
```

---

## Task 5: Convert metrics.py to Re-export Shim

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`

This is the key change that avoids updating 30+ files. The existing metrics.py becomes a thin re-export layer.

- [ ] **Step 1: Replace metrics.py content**

```python
# src/context_service/telemetry/metrics.py
"""Telemetry metrics - re-exports from recorder.py for backwards compatibility.

All functions are now backed by an in-process MetricsBuffer that flushes
to PostgreSQL, replacing the previous OTEL-based implementation.
"""

from __future__ import annotations

from context_service.telemetry.recorder import (
    ORPHAN_CHAINS_EXHAUSTED,
    ORPHAN_CHAINS_RECOVERED,
    get_buffer,
    get_db_pool,
    record_belief_confidence,
    record_cache_eviction,
    record_cache_hit,
    record_cache_miss,
    record_chain_evidence_modified,
    record_chain_feedback,
    record_chain_lookup,
    record_circuit_breaker_closed,
    record_circuit_breaker_opened,
    record_context_recall_size,
    record_db_query,
    record_embedding,
    record_embedding_cache_hit,
    record_embedding_cache_miss,
    record_engagement_latency,
    record_hard_query_detection,
    record_llm_call,
    record_llm_tokens,
    record_mcp_tool,
    record_node_confidence,
    record_orphan_chain_exhausted,
    record_orphan_chain_recovered,
    record_query_expansion,
    record_recall_depth,
    record_recall_latency,
    record_recall_result_count,
    record_reranking,
    record_request,
    record_source_tier_resolved,
    record_store_error,
    record_supersession_skipped,
    record_supersession_used,
    record_tool_error,
    set_db_pool,
    setup_metrics,
    track_active_request,
)

__all__ = [
    "ORPHAN_CHAINS_EXHAUSTED",
    "ORPHAN_CHAINS_RECOVERED",
    "get_buffer",
    "get_db_pool",
    "record_belief_confidence",
    "record_cache_eviction",
    "record_cache_hit",
    "record_cache_miss",
    "record_chain_evidence_modified",
    "record_chain_feedback",
    "record_chain_lookup",
    "record_circuit_breaker_closed",
    "record_circuit_breaker_opened",
    "record_context_recall_size",
    "record_db_query",
    "record_embedding",
    "record_embedding_cache_hit",
    "record_embedding_cache_miss",
    "record_engagement_latency",
    "record_hard_query_detection",
    "record_llm_call",
    "record_llm_tokens",
    "record_mcp_tool",
    "record_node_confidence",
    "record_orphan_chain_exhausted",
    "record_orphan_chain_recovered",
    "record_query_expansion",
    "record_recall_depth",
    "record_recall_latency",
    "record_recall_result_count",
    "record_reranking",
    "record_request",
    "record_source_tier_resolved",
    "record_store_error",
    "record_supersession_skipped",
    "record_supersession_used",
    "record_tool_error",
    "set_db_pool",
    "setup_metrics",
    "track_active_request",
]
```

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/context_service/telemetry/metrics.py`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/telemetry/metrics.py
git commit -m "refactor(telemetry): convert metrics.py to re-export shim"
```

---

## Task 6: Convert tracing.py to No-op Stubs

**Files:**
- Modify: `src/context_service/telemetry/tracing.py`

- [ ] **Step 1: Replace tracing.py with no-op implementations**

```python
# src/context_service/telemetry/tracing.py
"""Tracing stubs - no-op implementations replacing OTEL tracing."""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


def traced(
    name: str | None = None,
    *,
    capture_args: list[str] | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, R]]], Callable[P, Coroutine[Any, Any, R]]]:
    """No-op decorator replacing OTEL tracing."""

    def decorator(func: Callable[P, Coroutine[Any, Any, R]]) -> Callable[P, Coroutine[Any, Any, R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def setup_tracing(service_name: str = "context-service") -> None:
    """No-op - tracing disabled."""
    pass


def instrument_fastapi(app: object) -> None:
    """No-op - FastAPI instrumentation disabled."""
    pass
```

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/context_service/telemetry/tracing.py`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/telemetry/tracing.py
git commit -m "refactor(telemetry): replace tracing.py with no-op stubs"
```

---

## Task 7: Add PostgresResource to Dagster Resources

**Files:**
- Modify: `src/context_service/pipelines/resources.py`

- [ ] **Step 1: Add PostgresResource class**

Add after the imports and before MemgraphResource:

```python
class PostgresResource(dg.ConfigurableResource):  # type: ignore[type-arg]
    """Wraps asyncpg connection pool for Dagster jobs."""

    database_url: str

    _pool: asyncpg.Pool | None = PrivateAttr(default=None)

    @contextmanager
    def get_pool(self) -> Generator[asyncpg.Pool, None, None]:
        """Get or create asyncpg pool."""
        import asyncpg

        async def _create() -> asyncpg.Pool:
            return await asyncpg.create_pool(self.database_url)

        async def _close(pool: asyncpg.Pool) -> None:
            await pool.close()

        if self._pool is None:
            self._pool = asyncio.run(_create())

        try:
            yield self._pool
        finally:
            pass  # Pool stays open for resource lifetime

    def teardown_after_execution(self, _context: dg.InitResourceContext) -> None:
        if self._pool is not None:
            pool = self._pool
            self._pool = None
            _close_async(pool.close())
```

- [ ] **Step 2: Add import for Generator and contextmanager**

```python
from collections.abc import Generator
from contextlib import contextmanager
```

- [ ] **Step 3: Add postgres to build_default_resources**

```python
def build_default_resources() -> dict[str, dg.ConfigurableResource]:
    settings: Settings = get_settings()
    # ... existing code ...
    
    return {
        "postgres": PostgresResource(database_url=settings.database_url),
        "memgraph": MemgraphResource(...),
        # ... rest unchanged
    }
```

- [ ] **Step 4: Add to __all__**

```python
__all__ = [
    "PostgresResource",
    # ... rest
]
```

- [ ] **Step 5: Run type check**

Run: `uv run mypy src/context_service/pipelines/resources.py`

Expected: No errors (or asyncpg stub warnings)

- [ ] **Step 6: Commit**

```bash
git add src/context_service/pipelines/resources.py
git commit -m "feat(dagster): add PostgresResource for telemetry jobs"
```

---

## Task 8: Create Telemetry Gauges Dagster Job

**Files:**
- Create: `src/context_service/pipelines/jobs/telemetry_gauges.py`

- [ ] **Step 1: Create telemetry_gauges.py**

```python
# src/context_service/pipelines/jobs/telemetry_gauges.py
"""Dagster job for periodic storage gauge snapshots."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg


_LIST_SILOS = "SELECT DISTINCT silo_id FROM silo_config"

_COUNT_NODES = """
MATCH (n)
WHERE n.silo_id = $silo_id
RETURN
    sum(CASE WHEN n:Passage OR n:Utterance OR n:Event THEN 1 ELSE 0 END) AS memory,
    sum(CASE WHEN n:Claim THEN 1 ELSE 0 END) AS knowledge,
    sum(CASE WHEN n:Belief OR n:Commitment THEN 1 ELSE 0 END) AS wisdom
"""

_COUNT_EDGES = """
MATCH ()-[r]-()
WHERE r.silo_id = $silo_id OR startNode(r).silo_id = $silo_id
RETURN count(r) AS edges
"""


@dg.op(required_resource_keys={"postgres", "memgraph", "qdrant"})
def snapshot_storage_gauges(context: dg.OpExecutionContext) -> dict[str, Any]:
    """Snapshot storage metrics for all silos."""
    from context_service.pipelines.resources import MemgraphResource, PostgresResource, QdrantResource

    postgres: PostgresResource = context.resources.postgres
    memgraph: MemgraphResource = context.resources.memgraph
    qdrant: QdrantResource = context.resources.qdrant

    async def _run() -> dict[str, int]:
        store = await memgraph.store()
        qd_client = qdrant.client()

        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                rows = await conn.fetch(_LIST_SILOS)
                silo_ids = [str(row["silo_id"]) for row in rows]

            total = 0
            for silo_id in silo_ids:
                # Query Memgraph for node counts
                node_rows = await store.execute_query(_COUNT_NODES, {"silo_id": silo_id})
                node_row = node_rows[0] if node_rows else {}

                edge_rows = await store.execute_query(_COUNT_EDGES, {"silo_id": silo_id})
                edge_count = edge_rows[0].get("edges", 0) if edge_rows else 0

                # Query Qdrant for collection stats
                try:
                    collection_info = await qd_client.get_collection(f"silo_{silo_id}")
                    qd_points = collection_info.points_count or 0
                except Exception:
                    qd_points = 0

                # Insert gauge
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO service_gauges (
                            silo_id,
                            node_count_memory, node_count_knowledge, node_count_wisdom,
                            edge_count, qdrant_point_count
                        ) VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        silo_id,
                        node_row.get("memory", 0),
                        node_row.get("knowledge", 0),
                        node_row.get("wisdom", 0),
                        edge_count,
                        qd_points,
                    )

                context.log.info(f"telemetry_gauges: silo={silo_id}")
                total += 1

            return {"silos_processed": total}

    return asyncio.run(_run())


@dg.job(name="telemetry_gauges", tags={"schedule_type": "maintenance"})
def telemetry_gauges_job() -> None:
    """Hourly storage gauge snapshots."""
    snapshot_storage_gauges()
```

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/context_service/pipelines/jobs/telemetry_gauges.py`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/pipelines/jobs/telemetry_gauges.py
git commit -m "feat(dagster): add telemetry gauges snapshot job"
```

---

## Task 9: Create Telemetry Prune Dagster Job

**Files:**
- Create: `src/context_service/pipelines/jobs/telemetry_prune.py`

- [ ] **Step 1: Create telemetry_prune.py**

```python
# src/context_service/pipelines/jobs/telemetry_prune.py
"""Dagster job for telemetry data retention pruning."""

from __future__ import annotations

import asyncio

import dagster as dg


@dg.op(required_resource_keys={"postgres"})
def prune_service_metrics(context: dg.OpExecutionContext) -> int:
    """Delete service_metrics older than 90 days."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM service_metrics WHERE bucket < now() - INTERVAL '90 days'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted = asyncio.run(_run())
    context.log.info(f"prune_service_metrics: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_errors(context: dg.OpExecutionContext) -> int:
    """Delete expired service_errors."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM service_errors WHERE expires_at < now()"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted = asyncio.run(_run())
    context.log.info(f"prune_service_errors: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_service_gauges(context: dg.OpExecutionContext) -> int:
    """Delete service_gauges older than 1 year."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM service_gauges WHERE measured_at < now() - INTERVAL '1 year'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted = asyncio.run(_run())
    context.log.info(f"prune_service_gauges: deleted={deleted}")
    return deleted


@dg.op(required_resource_keys={"postgres"})
def prune_beacon_events(context: dg.OpExecutionContext) -> int:
    """Delete beacon_events older than 90 days."""
    from context_service.pipelines.resources import PostgresResource

    postgres: PostgresResource = context.resources.postgres

    async def _run() -> int:
        with postgres.get_pool() as pool:
            async with pool.acquire() as conn:
                result = await conn.execute(
                    "DELETE FROM beacon_events WHERE received_at < now() - INTERVAL '90 days'"
                )
                count = int(result.split()[-1]) if result else 0
                return count

    deleted = asyncio.run(_run())
    context.log.info(f"prune_beacon_events: deleted={deleted}")
    return deleted


@dg.job(name="telemetry_prune", tags={"schedule_type": "maintenance"})
def telemetry_prune_job() -> None:
    """Daily retention pruning for telemetry tables."""
    prune_service_metrics()
    prune_service_errors()
    prune_service_gauges()
    prune_beacon_events()
```

- [ ] **Step 2: Run type check**

Run: `uv run mypy src/context_service/pipelines/jobs/telemetry_prune.py`

Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/pipelines/jobs/telemetry_prune.py
git commit -m "feat(dagster): add telemetry retention pruning job"
```

---

## Task 10: Register Dagster Jobs and Schedules

**Files:**
- Modify: `src/context_service/pipelines/definitions.py`
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Update definitions.py**

Add imports:
```python
from context_service.pipelines.jobs.telemetry_gauges import telemetry_gauges_job
from context_service.pipelines.jobs.telemetry_prune import telemetry_prune_job
```

Update jobs list:
```python
jobs=[causal_tombstone_job, groundskeeper_nightly, sage_validator_job, telemetry_gauges_job, telemetry_prune_job],
```

- [ ] **Step 2: Update schedules.py**

Add schedules:
```python
from context_service.pipelines.jobs.telemetry_gauges import telemetry_gauges_job
from context_service.pipelines.jobs.telemetry_prune import telemetry_prune_job

telemetry_gauges_schedule = dg.ScheduleDefinition(
    job=telemetry_gauges_job,
    cron_schedule="0 * * * *",  # hourly
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

telemetry_prune_schedule = dg.ScheduleDefinition(
    job=telemetry_prune_job,
    cron_schedule="0 3 * * *",  # daily at 3am
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
```

Add to `all_schedules` list.

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/pipelines/`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/definitions.py src/context_service/pipelines/schedules.py
git commit -m "feat(dagster): register telemetry jobs and schedules"
```

---

## Task 11: Wire Flush Task into FastAPI

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Find lifespan context manager**

Run: `grep -n "lifespan\|asynccontextmanager" src/context_service/api/app.py | head -10`

- [ ] **Step 2: Add imports at top of file**

```python
import asyncio
from context_service.telemetry.metrics import setup_metrics, get_buffer, set_db_pool
from context_service.telemetry.flush import flush_metrics_to_db
```

- [ ] **Step 3: Add flush task after pool creation in lifespan**

After `app.state.db_pool = pool`:

```python
# Initialize telemetry
setup_metrics()
set_db_pool(pool)

# Start background flush task
async def periodic_flush() -> None:
    while True:
        await asyncio.sleep(60)
        buffer = get_buffer()
        if buffer is not None:
            try:
                await flush_metrics_to_db(pool, buffer)
            except Exception:
                logger.exception("metrics_flush_failed")

flush_task = asyncio.create_task(periodic_flush())
```

- [ ] **Step 4: Cancel flush task in lifespan cleanup**

Before `yield` ends, add cleanup:

```python
# After yield, cleanup:
flush_task.cancel()
try:
    await flush_task
except asyncio.CancelledError:
    pass

# Final flush before shutdown
buffer = get_buffer()
if buffer is not None:
    await flush_metrics_to_db(pool, buffer)
```

- [ ] **Step 5: Remove OTEL setup calls**

Remove calls to:
- `setup_tracing()`
- `instrument_fastapi(app)`

And remove their imports if no longer used.

- [ ] **Step 6: Run type check**

Run: `uv run mypy src/context_service/api/app.py`

Expected: No errors

- [ ] **Step 7: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(api): wire telemetry flush task into FastAPI lifespan"
```

---

## Task 12: Remove SigNoz Infrastructure

**Files:**
- Delete: `infra/components/signoz.py`
- Modify: `infra/components/__init__.py`
- Modify: `infra/__main__.py`

- [ ] **Step 1: Delete signoz.py**

```bash
git rm infra/components/signoz.py
```

- [ ] **Step 2: Update components/__init__.py**

Remove `SignozHost` from imports and `__all__`.

- [ ] **Step 3: Update __main__.py**

Remove:
- `SignozHost` import
- `signoz_host = SignozHost(...)` instantiation
- `signoz_ip=...` parameter from InternalDNS
- `pulumi.export("signoz_hostname", ...)`
- OTEL env vars: `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_INSECURE`, `OTEL_SERVICE_NAME`

- [ ] **Step 4: Verify Pulumi syntax**

Run: `cd infra && uv run python -c "import __main__"`

Expected: No import errors

- [ ] **Step 5: Commit**

```bash
git add infra/
git commit -m "infra: remove SigNoz component and OTEL env vars"
```

---

## Task 13: Remove OTEL Dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Remove OTEL packages from dependencies**

Remove these lines:
```
"opentelemetry-api>=1.25",
"opentelemetry-sdk>=1.25",
"opentelemetry-exporter-otlp>=1.25",
"opentelemetry-instrumentation-fastapi>=0.46b0",
"opentelemetry-instrumentation-httpx>=0.46b0",
"opentelemetry-instrumentation-redis>=0.46b0",
```

- [ ] **Step 2: Sync dependencies**

Run: `uv sync`

- [ ] **Step 3: Run tests to verify no import errors**

Run: `uv run pytest tests/unit/telemetry/ -v`

Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: remove opentelemetry packages"
```

---

## Task 14: Final Verification

- [ ] **Step 1: Run full check**

Run: `just ci`

Expected: All checks pass

- [ ] **Step 2: Run migration locally**

Run: `just db-migrate`

Expected: Migration 0014 applies successfully

- [ ] **Step 3: Verify telemetry buffer works**

```bash
uv run python -c "
from context_service.telemetry.metrics import setup_metrics, record_mcp_tool, get_buffer
setup_metrics()
record_mcp_tool('remember', 150.0, silo_id='test')
buffer = get_buffer()
rows = buffer.flush()
print(f'Flushed {len(rows)} rows: {rows}')
"
```

Expected: Shows 1 row with tool.remember metric

- [ ] **Step 4: Commit any fixes**

---

## Done Criteria

- [ ] Migration `0014` creates `service_metrics`, `service_errors`, `service_gauges` tables
- [ ] `MetricsBuffer` aggregates metrics in-process
- [ ] Background task flushes to PG every 60 seconds
- [ ] `metrics.py` is a re-export shim (all existing imports work)
- [ ] `tracing.py` provides no-op `@traced` decorator
- [ ] Dagster job snapshots storage gauges hourly
- [ ] Dagster job prunes old telemetry daily
- [ ] SigNoz component removed from infra
- [ ] OTEL dependencies removed from pyproject.toml
- [ ] `just ci` passes

---

## Out of Scope

- Metabase dashboard configuration (manual setup)
- Alerting (use Cloud Monitoring)
- Real-time metrics (aggregation is per-minute)
