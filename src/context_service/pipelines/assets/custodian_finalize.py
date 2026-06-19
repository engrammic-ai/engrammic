"""Dagster asset: custodian finalize — promote committed claims to :Finding nodes via R2 consensus."""

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


_BATCH_SIZE = 100

_SCAN_PROMOTABLE_COMMITMENTS = """
MATCH (c:Claim:Commitment {silo_id: $silo_id})
OPTIONAL MATCH (c)-[:PROMOTED_TO]->(f:Finding)
WITH c, f
WHERE f IS NULL
RETURN c.id AS commitment_id
LIMIT $batch_size
"""


@dg.asset(
    name="custodian_finalize",
    partitions_def=silo_partitions,
    deps=["claim_to_fact_promotion"],
    description="Promote :Claim:Commitment nodes to :Finding via R2 consensus per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "custodian_finalize"},
)
def custodian_finalize(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Scan commitments with R2 consensus chains and promote to :Finding nodes."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int]:
        from collections import defaultdict

        from context_service.custodian.consensus_promotion import promote_consensus_to_finding
        from context_service.db.queries import BATCH_GET_CHAINS_BY_COMMITMENTS
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_raw = MemgraphClient(driver)
        mg_store = await memgraph.store()

        rows = await mg_raw.execute_query(
            _SCAN_PROMOTABLE_COMMITMENTS,
            {"silo_id": silo_id, "batch_size": _BATCH_SIZE},
        )
        if not rows:
            return 0, 0

        commitment_ids = [str(row["commitment_id"]) for row in rows]

        # Batch fetch all chains for all commitments (N+1 fix)
        chain_rows = await mg_raw.execute_query(
            BATCH_GET_CHAINS_BY_COMMITMENTS,
            {"commitment_ids": commitment_ids, "silo_id": silo_id},
        )

        # Group chains by commitment_id client-side
        chains_by_commitment: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for c in chain_rows:
            cid = str(c.get("commitment_id", ""))
            chains_by_commitment[cid].append(c)

        clusters_processed = 0
        findings_created = 0

        for commitment_id in commitment_ids:
            commitment_chains = chains_by_commitment.get(commitment_id, [])
            if not commitment_chains:
                continue

            distinct_agents = len(
                {
                    c.get("produced_by_agent_id")
                    for c in commitment_chains
                    if c.get("produced_by_agent_id")
                }
            )
            if distinct_agents < 2:
                continue

            chain_ids = [str(c["id"]) for c in commitment_chains]
            try:
                await promote_consensus_to_finding(
                    memgraph=mg_store,
                    commitment_id=commitment_id,
                    contributing_chain_ids=chain_ids,
                    silo_id=silo_id,
                )
                findings_created += 1
                clusters_processed += 1
            except Exception as exc:
                context.log.warning(
                    f"promote_consensus_to_finding failed for commitment={commitment_id}: {exc}"
                )

        return clusters_processed, findings_created

    clusters_processed, findings_created = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} clusters_processed={clusters_processed} "
        f"findings_created={findings_created} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "clusters_processed": clusters_processed,
            "findings_created": findings_created,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "clusters_processed": dg.MetadataValue.int(clusters_processed),
            "findings_created": dg.MetadataValue.int(findings_created),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
