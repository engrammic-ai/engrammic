"""Dagster asset: chain stitcher — verify cross-cluster supersession chains after finalize."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
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
    name="chain_stitch",
    partitions_def=silo_partitions,
    deps=["custodian_finalize"],
    description="Verify cross-cluster supersession chains and identify terminal nodes per silo.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=5.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "chain_stitch"},
)
def chain_stitch(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Run chain stitching pass after custodian finalize completes."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, list[str]]:
        from context_service.custodian.chain_stitcher import stitch_cross_cluster_chains

        store = await memgraph.store()
        result = await stitch_cross_cluster_chains(store=store, silo_id=silo_id)
        return result.chains_found, result.terminals_found, result.edges_verified, result.errors

    chains_found, terminals_found, edges_verified, errors = _run_async(_run())
    duration_s = time.monotonic() - t0

    for err in errors:
        context.log.warning(f"chain_stitch silo={silo_id}: {err}")

    context.log.info(
        f"silo={silo_id} chains_found={chains_found} terminals_found={terminals_found} "
        f"edges_verified={edges_verified} errors={len(errors)} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "chains_found": chains_found,
            "terminals_found": terminals_found,
            "edges_verified": edges_verified,
            "errors": len(errors),
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "chains_found": dg.MetadataValue.int(chains_found),
            "terminals_found": dg.MetadataValue.int(terminals_found),
            "edges_verified": dg.MetadataValue.int(edges_verified),
            "errors": dg.MetadataValue.int(len(errors)),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
