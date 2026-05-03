"""Retention sweep Dagster asset."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource


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
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        from context_service.engine.memgraph_store import MemgraphStore
        store = MemgraphStore(mg_client)
        settings = get_settings()
        policy = RetentionPolicy.from_settings(settings)
        service = RetentionService(store=store, policy=policy)
        return await service.run_sweep(silo_id)

    result: dict[str, Any] = asyncio.run(_run())

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
