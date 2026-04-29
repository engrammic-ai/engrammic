"""Dagster run-status sensor: push exhausted-retry failures into the poison queue."""

import asyncio

import dagster as dg
from dagster import RunStatusSensorContext

from context_service.pipelines.poison_queue import PoisonQueue
from context_service.pipelines.resources import RedisResource

MAX_RETRIES = 3


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    name="poison_queue_sensor",
    description="Pushes failed Dagster run metadata into a Redis-backed poison queue for triage.",
    minimum_interval_seconds=30,
)
def poison_queue_sensor(
    context: RunStatusSensorContext,
    redis: RedisResource,
) -> None:
    """On run failure, push to poison queue only after retries are exhausted."""
    run = context.dagster_run
    retry_number = int(run.tags.get("dagster/retry_number", "0"))
    if retry_number < MAX_RETRIES:
        context.log.info(
            f"poison_queue: skipping run {run.run_id} (retry {retry_number}/{MAX_RETRIES})"
        )
        return

    run_id: str = run.run_id
    event = context.dagster_event
    error_info = getattr(event, "event_specific_data", None) if event is not None else None
    error_str = str(error_info) if error_info else "unknown"
    step_key = getattr(event, "step_key", "") or "" if event is not None else ""

    async def _push() -> None:
        raw = await redis.client()
        queue = PoisonQueue(raw)
        await queue.push(
            run_id=run_id,
            asset_key=step_key or "unknown",
            error=error_str,
        )

    asyncio.run(_push())
    context.log.info(f"poison_queue: queued run {run_id} step={step_key!r}")
