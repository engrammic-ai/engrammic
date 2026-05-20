"""Retention sweep Dagster asset."""

import asyncio
import concurrent.futures
import json
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

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
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Run retention sweep for all silos per retention policy.

    Reads silo_id from the partition key when running partitioned;
    callers that run this asset unpartitioned must supply a silo_id via
    run config (see RetentionSweepConfig).

    Per-silo retention overrides are loaded from the Silo node's
    ``silo_config`` property and resolved via SiloConfig.resolve() so that
    each silo's settings take precedence over the global defaults.
    """
    silo_id: str = context.partition_key

    async def _run() -> dict[str, Any]:
        from context_service.config.settings import get_settings
        from context_service.models.silo import SiloConfig
        from context_service.retention import RetentionPolicy, RetentionService

        store = await memgraph.store()
        settings = get_settings()

        # Fetch per-silo config from the Silo node (system-level query; no
        # org_id needed because silo_id is a globally unique UUID).
        rows: list[dict[str, Any]] = await store.execute_query(
            "MATCH (s:Silo {id: $silo_id}) RETURN s.silo_config AS silo_config",
            {"silo_id": silo_id},
        )

        silo_config: SiloConfig
        if rows and rows[0].get("silo_config"):
            raw = rows[0]["silo_config"]
            data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
            silo_config = SiloConfig.from_metadata_dict(data)
        else:
            silo_config = SiloConfig()

        resolved = silo_config.resolve(settings)
        policy = RetentionPolicy.from_resolved(resolved)

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
