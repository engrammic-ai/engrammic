"""Dagster schedule definitions for context-service.

Both schedules yield one RunRequest per active silo by querying Memgraph at
evaluation time. Using DynamicPartitionsDefinition means we can't use
build_schedule_from_partitioned_job; instead we emit per-partition RunRequests
directly from the schedule body.
"""

import asyncio
from collections.abc import Iterator
from typing import Any

import dagster as dg
from dagster import ScheduleEvaluationContext

from context_service.pipelines.resources import MemgraphResource

_LIST_ACTIVE_SILOS = """
MATCH (d:Document)
RETURN DISTINCT d.silo_id AS silo_id
"""


def _fetch_silo_ids(memgraph: MemgraphResource) -> list[str]:
    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    return asyncio.run(_run())


@dg.schedule(
    cron_schedule="0 4 * * *",
    name="clustering_schedule",
    target=dg.AssetSelection.assets("clustering"),
    description="Daily off-peak (04:00 UTC) clustering run per active silo.",
    execution_timezone="UTC",
)
def clustering_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one clustering RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"clustering:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 * * * *",
    name="fact_promotion_schedule",
    target=dg.AssetSelection.assets("claim_to_fact_promotion"),
    description="Hourly fact-promotion sweep per active silo.",
    execution_timezone="UTC",
)
def fact_promotion_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one fact-promotion RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"fact_promotion:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="*/15 * * * *",
    name="custodian_visit_schedule",
    target=dg.AssetSelection.assets("custodian_visit"),
    description="Every 15 minutes: custodian visit sweep per active silo.",
    execution_timezone="UTC",
)
def custodian_visit_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one custodian_visit RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"custodian_visit:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 * * * *",
    name="heat_schedule",
    target=dg.AssetSelection.assets("heat"),
    description="Hourly heat scoring per active silo.",
    execution_timezone="UTC",
)
def heat_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one heat RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"heat:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 * * * *",
    name="reasoning_compaction_schedule",
    target=dg.AssetSelection.assets("reasoning_compaction"),
    description="Hourly reasoning-chain compaction per active silo.",
    execution_timezone="UTC",
)
def reasoning_compaction_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one compaction RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"reasoning_compaction:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 3 * * *",
    name="retention_schedule",
    target=dg.AssetSelection.assets("retention_sweep"),
    description="Daily retention sweep (03:00 UTC) per active silo.",
    execution_timezone="UTC",
)
def retention_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one retention RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"retention:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


all_schedules: list[Any] = [
    clustering_schedule,
    fact_promotion_schedule,
    custodian_visit_schedule,
    heat_schedule,
    reasoning_compaction_schedule,
    retention_schedule,
]

__all__ = [
    "all_schedules",
    "clustering_schedule",
    "fact_promotion_schedule",
    "custodian_visit_schedule",
    "heat_schedule",
    "reasoning_compaction_schedule",
    "retention_schedule",
]
