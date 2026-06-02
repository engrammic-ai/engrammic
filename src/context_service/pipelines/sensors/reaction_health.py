"""Dagster sensors for monitoring Taskiq reaction queue health.

Two sensors:
- reaction_queue_depth_sensor: checks main queue depth per silo, warns on backlog
- reaction_dlq_sensor: checks dead letter queues, alerts when items are present

Neither sensor triggers a Dagster run. They emit structured log messages that
surface in the Dagster UI and can be consumed by alerting infrastructure.
"""

from __future__ import annotations

import asyncio

import dagster as dg

from context_service.pipelines.resources import RedisResource

# Default thresholds. Override via sensor config when launching from the UI.
_DEFAULT_QUEUE_DEPTH_THRESHOLD = 100
_DEFAULT_DLQ_ALERT_THRESHOLD = 1

# Redis key patterns for silo queue discovery
_QUEUE_KEY_PATTERN = "reactions:*:default"
_DLQ_KEY_PATTERN = "reactions:*:dlq"


async def _scan_queue_depths(
    redis_client: object,
    pattern: str,
) -> dict[str, int]:
    """Scan Redis for keys matching pattern and return key -> LLEN mapping."""
    from redis.asyncio import Redis

    client: Redis = redis_client  # type: ignore[assignment]
    depths: dict[str, int] = {}

    async for key in client.scan_iter(match=pattern, count=200):
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        raw_depth = client.llen(key_str)
        if asyncio.iscoroutine(raw_depth):
            depth = await raw_depth
        else:
            depth = raw_depth
        depths[key_str] = int(depth)

    return depths


def _extract_silo_id(key: str, suffix: str) -> str:
    """Extract silo_id from a reactions queue key.

    Key format: reactions:{silo_id}:{suffix}
    """
    prefix = "reactions:"
    if key.startswith(prefix) and key.endswith(f":{suffix}"):
        inner = key[len(prefix) : -len(f":{suffix}")]
        return inner
    return key


@dg.sensor(
    name="reaction_queue_depth_sensor",
    minimum_interval_seconds=60,
    description=(
        "Checks Taskiq reaction queue depths per silo. "
        "Logs a warning when depth exceeds the configured threshold. "
        "Does not trigger Dagster runs."
    ),
)
def reaction_queue_depth_sensor(
    context: dg.SensorEvaluationContext,
    redis: RedisResource,
) -> dg.SkipReason:
    """Poll all reaction queues and warn when any exceeds the backlog threshold."""

    threshold = int(
        context.cursor or str(_DEFAULT_QUEUE_DEPTH_THRESHOLD)
        if context.cursor and context.cursor.isdigit()
        else _DEFAULT_QUEUE_DEPTH_THRESHOLD
    )

    async def _check() -> dict[str, int]:
        client = await redis.client()
        return await _scan_queue_depths(client, _QUEUE_KEY_PATTERN)

    depths = asyncio.run(_check())

    if not depths:
        return dg.SkipReason("No reaction queues found in Redis")

    total_depth = sum(depths.values())
    over_threshold = {k: v for k, v in depths.items() if v > threshold}

    if over_threshold:
        for key, depth in sorted(over_threshold.items(), key=lambda kv: -kv[1]):
            silo_id = _extract_silo_id(key, "default")
            context.log.warning(
                f"reaction_queue_backlog silo={silo_id} depth={depth} threshold={threshold}"
            )
        context.log.warning(
            f"reaction_queue_summary queues_over_threshold={len(over_threshold)} "
            f"total_depth={total_depth}"
        )
    else:
        context.log.info(
            f"reaction_queue_ok total_depth={total_depth} queues={len(depths)} "
            f"threshold={threshold}"
        )

    return dg.SkipReason(
        f"Checked {len(depths)} queues; total_depth={total_depth}; "
        f"over_threshold={len(over_threshold)}"
    )


@dg.sensor(
    name="reaction_dlq_sensor",
    minimum_interval_seconds=120,
    description=(
        "Checks Taskiq reaction dead letter queues per silo. "
        "Logs an error when any DLQ contains items. "
        "Does not trigger Dagster runs."
    ),
)
def reaction_dlq_sensor(
    context: dg.SensorEvaluationContext,
    redis: RedisResource,
) -> dg.SkipReason:
    """Poll all dead letter queues and alert when any contain items."""

    alert_threshold = _DEFAULT_DLQ_ALERT_THRESHOLD

    async def _check() -> dict[str, int]:
        client = await redis.client()
        return await _scan_queue_depths(client, _DLQ_KEY_PATTERN)

    depths = asyncio.run(_check())

    if not depths:
        return dg.SkipReason("No reaction DLQs found in Redis")

    non_empty = {k: v for k, v in depths.items() if v >= alert_threshold}
    total_dlq_depth = sum(depths.values())

    if non_empty:
        for key, depth in sorted(non_empty.items(), key=lambda kv: -kv[1]):
            silo_id = _extract_silo_id(key, "dlq")
            context.log.error(
                f"reaction_dlq_non_empty silo={silo_id} depth={depth} action=manual_triage_required"
            )
        context.log.error(
            f"reaction_dlq_summary silos_with_dlq_items={len(non_empty)} "
            f"total_dlq_depth={total_dlq_depth}"
        )
    else:
        context.log.info(f"reaction_dlq_ok total_dlq_depth={total_dlq_depth}")

    return dg.SkipReason(
        f"Checked {len(depths)} DLQs; total_depth={total_dlq_depth}; non_empty={len(non_empty)}"
    )


__all__ = ["reaction_dlq_sensor", "reaction_queue_depth_sensor"]
