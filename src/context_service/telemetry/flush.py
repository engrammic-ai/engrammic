"""Background task to flush metrics buffer to PostgreSQL."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    import asyncpg

    from context_service.telemetry.buffer import MetricsBuffer

logger = structlog.get_logger(__name__)


async def flush_metrics_to_db(pool: asyncpg.Pool, buffer: MetricsBuffer) -> None:
    """Flush buffered metrics to service_metrics table.

    Uses peek/clear pattern to avoid data loss: buffer is only cleared after
    successful DB write. On conflict, counts and latency_sum are accumulated;
    percentiles reflect the first write to that bucket (acceptable tradeoff
    given 60s flush interval).
    """
    rows = buffer.peek()
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

    buffer.clear()
    logger.debug("metrics_flushed", row_count=len(rows))


