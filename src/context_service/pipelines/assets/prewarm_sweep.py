"""Dagster asset: trigger background work for warming nodes."""

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


FETCH_WARMING_NODES_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.materialization_level IN ['FULL', 'WARM']
  AND (n.prewarmed_at IS NULL OR n.prewarmed_at < $cutoff)
RETURN n.id AS id, n.effective_heat AS effective_heat,
       n.materialization_level AS level
ORDER BY n.effective_heat DESC
LIMIT 100
"""

MARK_PREWARMED_QUERY = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
SET n.prewarmed_at = $now
"""


@dg.asset(
    name="prewarm_sweep",
    deps=["heat_diffusion"],
    partitions_def=silo_partitions,
    description="Trigger background work for nodes transitioning to WARM/FULL",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "prewarm_sweep"},
)
def prewarm_sweep_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Find warming nodes and prioritize background work."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.config.diffusion import load_prewarm_config

        config = load_prewarm_config()

        if not config.enabled:
            context.log.info(f"silo={silo_id} prewarm disabled, skipping")
            return {"skipped": True}

        store = await memgraph.store()
        now = datetime.now(UTC)
        cutoff = (now - timedelta(hours=1)).isoformat()

        rows = await store.execute_query(
            FETCH_WARMING_NODES_QUERY,
            {"silo_id": silo_id, "cutoff": cutoff},
        )

        if not rows:
            return {"warming_nodes": 0}

        node_ids = [row["id"] for row in rows]

        await store.execute_write(
            MARK_PREWARMED_QUERY,
            {"silo_id": silo_id, "node_ids": node_ids, "now": now.isoformat()},
        )

        return {
            "warming_nodes": len(rows),
            "full_count": sum(1 for r in rows if r["level"] == "FULL"),
            "warm_count": sum(1 for r in rows if r["level"] == "WARM"),
        }

    output = _run_async(_run())
    duration_s = time.monotonic() - t0

    if output.get("skipped"):
        return dg.Output(value=output)

    context.log.info(
        f"silo={silo_id} warming_nodes={output['warming_nodes']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**output, "silo_id": silo_id, "duration_s": duration_s},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "warming_nodes": dg.MetadataValue.int(output["warming_nodes"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["prewarm_sweep_asset"]
