"""Dagster asset: custodian visit sweep per silo — runs the 4-phase visit loop over clusters."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.logging import set_dagster_context
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


_BATCH_SIZE = 20

_LIST_ACTIVE_CLUSTERS = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE c.level = 0
RETURN c.id AS cluster_id,
       c.level AS level,
       coalesce(c.node_count, 0) AS member_count,
       c.summary AS summary
ORDER BY coalesce(c.node_count, 0) DESC
LIMIT $batch_size
"""

_FETCH_CHILD_FINDINGS = """
MATCH (parent:Cluster {id: $cluster_id, silo_id: $silo_id})
MATCH (child:Cluster)-[:PART_OF]->(parent)
MATCH (f:Finding {scope: "cluster", silo_id: $silo_id})-[:ABOUT]->(child)
WHERE f.source = 'extraction' OR f.status = 'published'
RETURN f.subject AS summary
LIMIT 5
"""


@dg.asset(
    name="custodian_visit",
    partitions_def=silo_partitions,
    deps=["extraction", "embedding"],  # Soft deps - doesn't require inputs
    description="Run custodian 4-phase visit loop over active clusters per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "custodian_visit"},
)
def custodian_visit(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Visit each active cluster for the partition's silo and write commitment nodes."""
    set_dagster_context(context)
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, float]:
        import uuid

        from context_service.custodian.metrics import compute_cost_usd
        from context_service.custodian.models import VisitStatus
        from context_service.custodian.visit import run_visit
        from context_service.stores import MemgraphClient
        from context_service.stores.redis import RedisClient

        driver = await memgraph.driver()
        mg_raw = MemgraphClient(driver)
        mg_store = await memgraph.store()
        raw_redis = await redis.client()
        redis_client = RedisClient(raw_redis)

        cluster_rows = await mg_raw.execute_query(
            _LIST_ACTIVE_CLUSTERS,
            {"silo_id": silo_id, "batch_size": _BATCH_SIZE},
        )
        if not cluster_rows:
            return 0, 0, 0, 0.0

        visits = 0
        commitments_created = 0
        llm_calls = 0
        total_cost_usd = 0.0

        for row in cluster_rows:
            cluster_id = str(row["cluster_id"])
            member_count = int(row.get("member_count") or 0)
            naive_summary: str | None = row.get("summary")

            child_rows = await mg_raw.execute_query(
                _FETCH_CHILD_FINDINGS,
                {"cluster_id": cluster_id, "silo_id": silo_id},
            )
            child_summaries = [str(r["summary"]) for r in child_rows if r.get("summary")]

            pass_id = str(uuid.uuid4())
            try:
                result = await run_visit(
                    cluster_id=cluster_id,
                    org_id=silo_id,
                    silo_id=silo_id,
                    pass_id=pass_id,
                    cluster_level=str(row.get("level", 0)),
                    cluster_member_count=member_count,
                    naive_summary=naive_summary,
                    child_finding_summaries=child_summaries,
                    memgraph_client=mg_store,
                    redis_client=redis_client,
                )
                visits += 1

                if result.status == VisitStatus.COMPLETED and result.write_result is not None:
                    commitments_created += result.write_result.claims_committed

                phase_calls = len(result.usage_breakdown)
                llm_calls += phase_calls

                visit_cost = sum(
                    compute_cost_usd(u.model, u.input_tokens, u.output_tokens)
                    for u in result.usage_breakdown.values()
                )
                total_cost_usd += visit_cost

            except Exception as exc:
                context.log.warning(f"visit failed for cluster={cluster_id}: {exc}")

        return visits, commitments_created, llm_calls, total_cost_usd

    visits, commitments_created, llm_calls, cost_usd = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} visits={visits} commitments={commitments_created} "
        f"llm_calls={llm_calls} cost_usd={cost_usd:.4f} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "visits": visits,
            "commitments_created": commitments_created,
            "llm_calls": llm_calls,
            "cost_usd": cost_usd,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "visits": dg.MetadataValue.int(visits),
            "commitments_created": dg.MetadataValue.int(commitments_created),
            "llm_calls": dg.MetadataValue.int(llm_calls),
            "cost_usd": dg.MetadataValue.float(cost_usd),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
