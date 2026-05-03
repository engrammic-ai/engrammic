"""Dagster asset: clustering — Leiden community detection + hierarchical summaries per silo."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import (
    EmbeddingResource,
    LLMResource,
    MemgraphResource,
    QdrantResource,
    RedisResource,
)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="clustering",
    partitions_def=silo_partitions,
    ins={"custodian_finalize": dg.AssetIn("custodian_finalize")},
    description="Run Leiden clustering + hierarchical summaries for settled :Finding nodes per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "clustering"},
)
def clustering(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    qdrant: QdrantResource,
    redis: RedisResource,
    llm: LLMResource,
    embedding: EmbeddingResource,
    custodian_finalize: dg.Nothing,  # type: ignore[valid-type]  # noqa: ARG001 — Dagster dep marker, runtime sentinel
) -> dg.Output[dict[str, Any]]:
    """Detect communities via Leiden, build cluster hierarchy, generate LLM summaries, embed."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, float]:
        import uuid

        from context_service.clustering.job_store import ClusteringJobStore
        from context_service.clustering.models import ClusteringJob, ClusteringStatus
        from context_service.clustering.service import ClusteringService
        from context_service.stores.redis import RedisClient

        mg_client = await memgraph.store()
        cluster_qdrant = qdrant.qdrant_store()

        redis_conn = await redis.client()
        job_store = ClusteringJobStore(RedisClient(redis_conn))

        llm_client = llm.get_client()
        embedding_client = embedding.get_client()

        service = ClusteringService(
            memgraph=mg_client,
            llm=llm_client,
            job_store=job_store,
            embedding=embedding_client,
            cluster_qdrant=cluster_qdrant,
        )

        job = ClusteringJob(
            id=str(uuid.uuid4()),
            silo_id=silo_id,
            status=ClusteringStatus.PENDING,
        )

        try:
            await service.run_clustering(silo_id, job)
        finally:
            await cluster_qdrant.close()

        clusters_created = job.total_clusters or 0
        hierarchy_levels = len(job.level_counts or {})
        embeddings_upserted = clusters_created
        cost_usd = 0.0

        return clusters_created, hierarchy_levels, embeddings_upserted, cost_usd

    clusters_created, hierarchy_levels, embeddings_upserted, cost_usd = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} clusters_created={clusters_created} "
        f"hierarchy_levels={hierarchy_levels} embeddings_upserted={embeddings_upserted} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "clusters_created": clusters_created,
            "hierarchy_levels": hierarchy_levels,
            "embeddings_upserted": embeddings_upserted,
            "cost_usd": cost_usd,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "clusters_created": dg.MetadataValue.int(clusters_created),
            "hierarchy_levels": dg.MetadataValue.int(hierarchy_levels),
            "embeddings_upserted": dg.MetadataValue.int(embeddings_upserted),
            "cost_usd": dg.MetadataValue.float(cost_usd),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
