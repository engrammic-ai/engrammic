"""Retention sweep Dagster asset."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="retention_sweep",
    description="Tombstone and hard-delete nodes per retention policy.",
    compute_kind="memgraph",
    group_name="maintenance",
)
def retention_sweep(
    context: dg.AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Run retention sweep for all silos per retention policy.

    Reads silo_id from the partition key when running partitioned;
    callers that run this asset unpartitioned must supply a silo_id via
    run config (see RetentionSweepConfig).
    """
    silo_id: str = context.partition_key

    async def _run() -> dict[str, Any]:
        from context_service.config.settings import get_settings
        from context_service.retention import RetentionPolicy, RetentionService

        store = await memgraph.store()
        settings = get_settings()
        policy = RetentionPolicy.from_settings(settings)
        service = RetentionService(store=store, policy=policy)
        return await service.run_sweep(silo_id)

    result: dict[str, Any] = _run_async(_run())

    context.log.info(
        f"silo={silo_id} tombstoned={result['tombstoned']} "
        f"meta_tombstoned={result['meta_tombstoned']} deleted={result['deleted']}"
    )

    return dg.Output(
        value=result,
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "tombstoned": dg.MetadataValue.int(result["tombstoned"]),
            "meta_tombstoned": dg.MetadataValue.int(result["meta_tombstoned"]),
            "deleted": dg.MetadataValue.int(result["deleted"]),
            "run_id": dg.MetadataValue.text(result["run_id"]),
        },
    )


__all__ = ["retention_sweep"]
