"""Dagster asset: synthesise a :Belief node from a dense fact cluster."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="belief_synthesis",
    partitions_def=silo_partitions,
    description=(
        "Synthesise a :Belief node from a qualifying fact cluster.  "
        "Triggered by belief_synthesis_sensor when cluster density >= MIN_FACTS_FOR_BELIEF."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=5.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "belief_synthesis"},
)
def belief_synthesis_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Synthesise a belief for the cluster_id supplied via run tags."""
    silo_id: str = context.partition_key
    cluster_id: str = context.run_tags.get("cluster_id", "")
    if not cluster_id:
        raise ValueError(
            "belief_synthesis asset requires a 'cluster_id' run tag — "
            "was this triggered without the sensor?"
        )

    subject: str = context.run_tags.get("subject", "")
    t0 = time.monotonic()

    async def _run() -> str:
        from context_service.engine.synthesis import (
            check_belief_coverage,
            synthesize_belief,
        )

        store = await memgraph.store()

        if subject:
            existing = await check_belief_coverage(store, silo_id, subject)
            if existing:
                context.log.info(
                    f"belief_synthesis skipped — existing coverage found "
                    f"silo={silo_id} cluster={cluster_id} subject={subject!r} "
                    f"existing_belief={existing['belief_id']}"
                )
                return str(existing["belief_id"])

        llm_client = llm.get_client()

        return await synthesize_belief(store, cluster_id, silo_id, llm_client)

    belief_id = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"belief_synthesised silo={silo_id} cluster={cluster_id} "
        f"belief={belief_id} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "cluster_id": cluster_id,
            "belief_id": belief_id,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "cluster_id": dg.MetadataValue.text(cluster_id),
            "belief_id": dg.MetadataValue.text(belief_id),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
