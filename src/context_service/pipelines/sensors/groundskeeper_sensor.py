# src/context_service/pipelines/sensors/groundskeeper_sensor.py
"""Sensor-driven SAGE Groundskeeper.

Replaces the polling schedule with a sensor that only triggers runs when
Redis access_events or edge_access_events streams have pending data.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterator
from typing import TYPE_CHECKING

import dagster as dg

from context_service.pipelines.resources import RedisResource

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Minimum events needed to trigger a run (avoid noise from single events)
_MIN_PENDING_EVENTS = 5

# Sensor checks every 60 seconds
_SENSOR_INTERVAL_SECONDS = 60


async def _get_silos_with_pending_events(
    redis_client: Redis,
) -> dict[str, dict[str, int]]:
    """Scan Redis for silos with pending access events.

    Returns dict of silo_id -> {stream_type: pending_count}.
    Only includes silos with at least _MIN_PENDING_EVENTS pending.
    """
    silos: dict[str, dict[str, int]] = {}

    # Scan for access_events streams
    async for key in redis_client.scan_iter(match="silo:*:access_events", count=200):
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        # Extract silo_id from silo:{silo_id}:access_events
        parts = key_str.split(":")
        if len(parts) >= 3:
            silo_id = parts[1]
            length = await redis_client.xlen(key_str)
            if length >= _MIN_PENDING_EVENTS:
                if silo_id not in silos:
                    silos[silo_id] = {}
                silos[silo_id]["access_events"] = length

    # Scan for edge_access_events streams
    async for key in redis_client.scan_iter(match="silo:*:edge_access_events", count=200):
        key_str = key.decode() if isinstance(key, bytes) else str(key)
        parts = key_str.split(":")
        if len(parts) >= 3:
            silo_id = parts[1]
            length = await redis_client.xlen(key_str)
            if length >= _MIN_PENDING_EVENTS:
                if silo_id not in silos:
                    silos[silo_id] = {}
                silos[silo_id]["edge_access_events"] = length

    return silos


def _ensure_partition_exists(context: dg.SensorEvaluationContext, silo_id: str) -> None:
    """Ensure the silo_id partition exists in the dynamic partitions."""
    from context_service.pipelines.partitions import silo_partitions_def

    with contextlib.suppress(Exception):
        context.instance.add_dynamic_partitions(
            partitions_def_name=silo_partitions_def.name,
            partition_keys=[silo_id],
        )


@dg.sensor(
    name="groundskeeper_sensor",
    target=dg.AssetSelection.assets(
        "heat",
        "edge_heat",
        "heat_diffusion",
        "prewarm_sweep",
    ),
    minimum_interval_seconds=_SENSOR_INTERVAL_SECONDS,
    description=(
        "SAGE Groundskeeper sensor: watches Redis access event streams and "
        "triggers heat/maintenance runs only when pending events exist."
    ),
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def groundskeeper_sensor(
    context: dg.SensorEvaluationContext,
    redis: RedisResource,
) -> Iterator[dg.RunRequest | dg.SkipReason]:
    """Sensor that triggers groundskeeper runs based on Redis stream activity."""

    async def _check() -> dict[str, dict[str, int]]:
        client = await redis.client()
        return await _get_silos_with_pending_events(client)

    silos_with_work = asyncio.run(_check())

    if not silos_with_work:
        yield dg.SkipReason("No silos have pending access events")
        return

    context.log.info(
        f"groundskeeper_sensor found {len(silos_with_work)} silos with pending events"
    )

    for silo_id, event_counts in silos_with_work.items():
        total_events = sum(event_counts.values())
        _ensure_partition_exists(context, silo_id)

        context.log.info(
            f"groundskeeper_sensor silo={silo_id} pending_events={total_events} "
            f"streams={list(event_counts.keys())}"
        )

        yield dg.RunRequest(
            run_key=f"groundskeeper:{silo_id}:{context.cursor or '0'}",
            partition_key=silo_id,
            tags={
                "sage_job": "groundskeeper",
                "dagster/concurrency_key": silo_id,
                "pending_events": str(total_events),
            },
        )


__all__ = ["groundskeeper_sensor"]
