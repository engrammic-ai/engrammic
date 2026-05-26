# Service Metrics Schema

> **Status:** Draft
> **Goal:** Consolidate all telemetry to PostgreSQL, kill SigNoz, use Metabase for dashboards.

## Tables

### `service_metrics` - Aggregated operational metrics

Per-minute rollups of hosted service activity. Inserted by a background task.

```sql
CREATE TABLE service_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Time bucket (truncated to minute)
    bucket TIMESTAMPTZ NOT NULL,
    
    -- Dimension keys
    silo_id VARCHAR(255) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,  -- e.g., 'tool.remember', 'tool.recall', 'embedding.generate'
    
    -- Aggregated values
    count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    latency_sum_ms DOUBLE PRECISION NOT NULL DEFAULT 0,  -- for computing avg
    latency_p50_ms DOUBLE PRECISION,
    latency_p95_ms DOUBLE PRECISION,
    latency_max_ms DOUBLE PRECISION,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    
    UNIQUE (bucket, silo_id, metric_name)
);

-- Query patterns: time range + silo, time range + metric
CREATE INDEX idx_service_metrics_bucket ON service_metrics (bucket DESC);
CREATE INDEX idx_service_metrics_silo_bucket ON service_metrics (silo_id, bucket DESC);
CREATE INDEX idx_service_metrics_metric_bucket ON service_metrics (metric_name, bucket DESC);
```

**Metric names:**
- `tool.<name>` - MCP tool invocations (remember, learn, believe, recall, etc.)
- `embedding.generate` - embedding calls
- `llm.<model>` - LLM calls (custodian, synthesizer)
- `cache.hit`, `cache.miss` - cache performance
- `store.write`, `store.read` - storage operations

### `service_errors` - Error log (not aggregated)

Individual errors for debugging. Retained 30 days, then pruned.

```sql
CREATE TABLE service_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    silo_id VARCHAR(255) NOT NULL,
    
    -- Error details
    error_type VARCHAR(200) NOT NULL,  -- exception class name
    error_message TEXT,
    tool_name VARCHAR(100),            -- which tool failed, if applicable
    
    -- Context (JSONB for flexibility)
    context JSONB,                      -- request params, stack trace, etc.
    
    -- Pruning
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '30 days')
);

CREATE INDEX idx_service_errors_occurred ON service_errors (occurred_at DESC);
CREATE INDEX idx_service_errors_silo ON service_errors (silo_id, occurred_at DESC);
CREATE INDEX idx_service_errors_type ON service_errors (error_type, occurred_at DESC);
CREATE INDEX idx_service_errors_expires ON service_errors (expires_at);
```

### `service_gauges` - Point-in-time measurements

Periodic snapshots of storage size, node counts, etc. Inserted by Dagster job (hourly).

```sql
CREATE TABLE service_gauges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    measured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    silo_id VARCHAR(255) NOT NULL,
    
    -- Storage metrics
    node_count_memory INTEGER,
    node_count_knowledge INTEGER,
    node_count_wisdom INTEGER,
    edge_count INTEGER,
    
    -- Vector store
    qdrant_point_count INTEGER,
    qdrant_collection_size_bytes BIGINT,
    
    -- Graph store
    memgraph_vertex_count INTEGER,
    memgraph_edge_count INTEGER,
    
    UNIQUE (measured_at, silo_id)
);

CREATE INDEX idx_service_gauges_silo_time ON service_gauges (silo_id, measured_at DESC);
```

## Aggregation Strategy

### In-process buffering

```python
# In telemetry/buffer.py
from collections import defaultdict
from dataclasses import dataclass, field
import threading
import time

@dataclass
class MetricBucket:
    count: int = 0
    error_count: int = 0
    latencies: list[float] = field(default_factory=list)

class MetricsBuffer:
    """Thread-safe buffer for metric aggregation."""
    
    def __init__(self, flush_interval_seconds: int = 60):
        self._buckets: dict[tuple[str, str, str], MetricBucket] = defaultdict(MetricBucket)
        self._lock = threading.Lock()
        self._flush_interval = flush_interval_seconds
    
    def record(
        self,
        metric_name: str,
        silo_id: str,
        latency_ms: float | None = None,
        error: bool = False,
    ) -> None:
        bucket_time = self._truncate_to_minute(time.time())
        key = (bucket_time, silo_id, metric_name)
        
        with self._lock:
            bucket = self._buckets[key]
            bucket.count += 1
            if error:
                bucket.error_count += 1
            if latency_ms is not None:
                bucket.latencies.append(latency_ms)
    
    def flush(self) -> list[dict]:
        """Return aggregated metrics and clear buffer."""
        with self._lock:
            results = []
            for (bucket_time, silo_id, metric_name), bucket in self._buckets.items():
                latencies = sorted(bucket.latencies) if bucket.latencies else []
                results.append({
                    "bucket": bucket_time,
                    "silo_id": silo_id,
                    "metric_name": metric_name,
                    "count": bucket.count,
                    "error_count": bucket.error_count,
                    "latency_sum_ms": sum(latencies),
                    "latency_p50_ms": self._percentile(latencies, 50),
                    "latency_p95_ms": self._percentile(latencies, 95),
                    "latency_max_ms": max(latencies) if latencies else None,
                })
            self._buckets.clear()
            return results
```

### Flush to PostgreSQL

Background task runs every 60 seconds, calls `buffer.flush()`, bulk inserts to `service_metrics`.

```python
async def flush_metrics_to_db(pool: asyncpg.Pool, buffer: MetricsBuffer) -> None:
    rows = buffer.flush()
    if not rows:
        return
    
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO service_metrics (bucket, silo_id, metric_name, count, error_count,
                                         latency_sum_ms, latency_p50_ms, latency_p95_ms, latency_max_ms)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (bucket, silo_id, metric_name) DO UPDATE SET
                count = service_metrics.count + EXCLUDED.count,
                error_count = service_metrics.error_count + EXCLUDED.error_count,
                latency_sum_ms = service_metrics.latency_sum_ms + EXCLUDED.latency_sum_ms
            """,
            [(r["bucket"], r["silo_id"], r["metric_name"], r["count"], r["error_count"],
              r["latency_sum_ms"], r["latency_p50_ms"], r["latency_p95_ms"], r["latency_max_ms"])
             for r in rows]
        )
```

## Metabase Queries

### Tool usage over time
```sql
SELECT 
    date_trunc('hour', bucket) AS hour,
    metric_name,
    SUM(count) AS invocations,
    SUM(error_count) AS errors,
    AVG(latency_p95_ms) AS avg_p95_latency
FROM service_metrics
WHERE bucket > now() - INTERVAL '7 days'
  AND metric_name LIKE 'tool.%'
GROUP BY 1, 2
ORDER BY 1 DESC, 3 DESC;
```

### Active silos (daily)
```sql
SELECT 
    date_trunc('day', bucket) AS day,
    COUNT(DISTINCT silo_id) AS active_silos,
    SUM(count) AS total_operations
FROM service_metrics
WHERE bucket > now() - INTERVAL '30 days'
GROUP BY 1
ORDER BY 1 DESC;
```

### Error rate by tool
```sql
SELECT 
    metric_name,
    SUM(count) AS total,
    SUM(error_count) AS errors,
    ROUND(100.0 * SUM(error_count) / NULLIF(SUM(count), 0), 2) AS error_pct
FROM service_metrics
WHERE bucket > now() - INTERVAL '24 hours'
  AND metric_name LIKE 'tool.%'
GROUP BY 1
ORDER BY error_pct DESC;
```

## Retention & Pruning

| Table | Retention | Pruning method |
|-------|-----------|----------------|
| `service_metrics` | 90 days | Dagster job, `DELETE WHERE bucket < now() - '90 days'` |
| `service_errors` | 30 days | Dagster job, `DELETE WHERE expires_at < now()` |
| `service_gauges` | 1 year | Dagster job, `DELETE WHERE measured_at < now() - '1 year'` |
| `beacon_events` | 90 days | Dagster job (same as metrics) |

## Migration Plan

1. Add migration `0014_create_service_metrics_tables.py`
2. Implement `MetricsBuffer` in `src/context_service/telemetry/buffer.py`
3. Wire buffer into MCP tool wrappers
4. Add background flush task to FastAPI lifespan
5. Add Dagster job for `service_gauges` snapshots
6. Add Dagster job for retention pruning
7. Remove SigNoz from infra (`infra/components/signoz.py`, references in `__main__.py`)
8. Remove OTEL dependencies from `pyproject.toml`
9. Build Metabase dashboards

## Out of Scope

- Real-time alerting (use Cloud Monitoring for uptime checks)
- Distributed tracing (not needed for monolith)
- Per-request logging (use Cloud Logging for debugging)
