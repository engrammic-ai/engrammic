"""Dagster asset: synthesise a :Belief node from a dense fact cluster."""

import asyncio
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource


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

    t0 = time.monotonic()

    async def _run() -> str:
        from context_service.engine.memgraph_store import MemgraphStore
        from context_service.engine.synthesis import synthesize_belief
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        store = MemgraphStore(mg_client)
        llm_client = llm.get_client()

        return await synthesize_belief(store, cluster_id, silo_id, llm_client)

    belief_id = asyncio.run(_run())
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
