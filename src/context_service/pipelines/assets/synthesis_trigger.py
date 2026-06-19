"""Dagster asset: synthesis trigger per silo (CITE v2)."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.logging import set_dagster_context
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
    name="synthesis_trigger",
    partitions_def=silo_partitions,
    deps=["claim_to_fact_promotion"],
    description="Trigger belief synthesis by finding corroborating fact pairs per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "synthesis_trigger"},
)
def synthesis_trigger(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Find qualifying corroborating fact pairs in the partition's silo and emit synthesis requests."""
    set_dagster_context(context)
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> list[str]:
        from context_service.config.settings import get_settings
        from context_service.synthesis.trigger import trigger_synthesis

        graph_store = await memgraph.store()
        settings = get_settings()

        return await trigger_synthesis(graph_store, silo_id, settings.synthesis)

    request_ids = _run_async(_run())
    duration_s = time.monotonic() - t0
    count = len(request_ids)

    context.log.info(
        f"silo={silo_id} synthesis_requests={count} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "synthesis_requests_count": count,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "synthesis_requests_count": dg.MetadataValue.int(count),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
