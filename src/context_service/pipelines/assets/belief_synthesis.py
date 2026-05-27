"""Dagster asset: batch synthesise :Belief nodes from dense fact clusters."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.engine.synthesis import _get_min_facts_for_belief
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource

_LIST_PENDING_CLUSTERS = """
MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
WITH c, count(f) AS fact_count
WHERE fact_count >= $min_facts
OPTIONAL MATCH (c)<-[:SYNTHESIZED_FROM]-(b:Belief {silo_id: $silo_id})
WITH c, fact_count, b
WHERE b IS NULL
RETURN c.id AS cluster_id, fact_count
ORDER BY fact_count DESC
LIMIT $max_clusters
"""

_MAX_CLUSTERS_PER_RUN = 50


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


@dg.asset(
    name="belief_synthesis",
    partitions_def=silo_partitions,
    deps=["llm_pattern_detection"],
    description=(
        "Batch synthesise :Belief nodes from qualifying fact clusters. "
        "Processes up to 50 pending clusters per run."
    ),
    retry_policy=dg.RetryPolicy(max_retries=1, delay=10.0),
    tags={"dagster/concurrency_key": "belief_synthesis"},
)
def belief_synthesis_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Batch synthesise beliefs for all pending clusters in a silo."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.engine.synthesis import synthesize_belief
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()
        llm_client = llm.get_client()

        rows = await client.execute_query(
            _LIST_PENDING_CLUSTERS,
            {
                "silo_id": silo_id,
                "min_facts": _get_min_facts_for_belief(),
                "max_clusters": _MAX_CLUSTERS_PER_RUN,
            },
        )

        clusters = [
            {"cluster_id": str(r["cluster_id"]), "fact_count": int(r["fact_count"])} for r in rows
        ]

        if not clusters:
            context.log.info(f"belief_synthesis: no pending clusters for silo={silo_id}")
            return {"succeeded": 0, "failed": 0, "total": 0, "belief_ids": []}

        context.log.info(
            f"belief_synthesis: processing {len(clusters)} clusters for silo={silo_id}"
        )

        succeeded = 0
        failed = 0
        belief_ids: list[str] = []

        for cluster in clusters:
            cluster_id = str(cluster["cluster_id"])
            try:
                belief_id = await synthesize_belief(store, cluster_id, silo_id, llm_client)
                belief_ids.append(belief_id)
                succeeded += 1
                context.log.info(f"belief_synthesised cluster={cluster_id} belief={belief_id}")
            except Exception as e:
                failed += 1
                context.log.error(f"belief_synthesis failed cluster={cluster_id} error={e}")

        return {
            "succeeded": succeeded,
            "failed": failed,
            "total": len(clusters),
            "belief_ids": belief_ids,
        }

    result = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"belief_synthesis_batch complete silo={silo_id} "
        f"succeeded={result['succeeded']} failed={result['failed']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "succeeded": result["succeeded"],
            "failed": result["failed"],
            "total": result["total"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "succeeded": dg.MetadataValue.int(result["succeeded"]),
            "failed": dg.MetadataValue.int(result["failed"]),
            "total": dg.MetadataValue.int(result["total"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
