"""Dagster sensor: poll the Redis embed outbox and yield RunRequests when work is pending."""

from __future__ import annotations

import asyncio

import dagster as dg

from context_service.engine.outbox import OUTBOX_KEY
from context_service.pipelines.resources import RedisResource

_POLL_INTERVAL_SECONDS = 15
_MIN_QUEUE_DEPTH = 1


@dg.sensor(
    name="outbox_embed_sensor",
    job_name="outbox_embed_job",
    minimum_interval_seconds=_POLL_INTERVAL_SECONDS,
    description=(
        "Polls the Redis outbox:embed list. Yields a RunRequest whenever the "
        "queue depth is above the threshold so outbox_embed_job drains it."
    ),
)
def outbox_embed_sensor(
    context: dg.SensorEvaluationContext,
    redis: RedisResource,
) -> dg.SensorResult:
    """Check outbox depth and request a run when items are waiting."""

    async def _depth() -> int:
        client = await redis.client()
        result = await client.llen(OUTBOX_KEY)  # type: ignore[misc]
        return int(result)

    try:
        depth = asyncio.run(_depth())
    except Exception as exc:
        context.log.warning(f"outbox_embed_sensor: redis check failed: {exc}")
        return dg.SensorResult(run_requests=[])

    if depth < _MIN_QUEUE_DEPTH:
        return dg.SensorResult(run_requests=[], cursor=context.cursor or "0")

    context.log.info(f"outbox_embed_sensor: queue depth={depth}, triggering run")

    run_request = dg.RunRequest(
        run_key=f"outbox_embed:{context.cursor or '0'}:{depth}",
        tags={"dagster/concurrency_key": "outbox_embed"},
    )

    return dg.SensorResult(
        run_requests=[run_request],
        cursor=str(depth),
    )


__all__ = ["outbox_embed_sensor"]
