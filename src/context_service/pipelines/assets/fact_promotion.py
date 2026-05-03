"""Dagster asset: batch :Claim -> :Fact promotion per silo."""

import asyncio
import concurrent.futures
import time
import uuid
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

_BATCH_SIZE = 500

_SCAN_UNPROMOTED_CLAIMS = """
MATCH (c:Claim)
WHERE c.silo_id = $silo_id AND NOT c:Fact
RETURN c.id AS id, properties(c) AS props
LIMIT $batch_size
"""

# Batch evidence count for all claim IDs in one RTT.
# Returns one row per claim: {cid, cnt}.
_BATCH_COUNT_EVIDENCE = """
UNWIND $claim_ids AS cid
MATCH (c:Claim {id: cid, silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->()
RETURN cid, count(*) AS cnt
"""

# Batch corroborations for all claim IDs in one RTT.
# Returns one row per (claim, corroborating-claim) pair: {cid, props}.
# Corroborating claims = other :Claim nodes sharing at least one reference/
# derived-from target with this claim.
_BATCH_FETCH_CORROBORATIONS = """
UNWIND $claim_ids AS cid
MATCH (c:Claim {id: cid, silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->(ref)
MATCH (other:Claim {silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->(ref)
WHERE other.id <> cid
RETURN DISTINCT cid, properties(other) AS props
"""


@dg.asset(
    name="claim_to_fact_promotion",
    partitions_def=silo_partitions,
    ins={"custodian_visit": dg.AssetIn("custodian_visit")},
    description="Batch-promote :Claim nodes to :Fact per silo using EAG R1/R2 rules.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "claim_to_fact_promotion"},
)
def claim_to_fact_promotion(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    custodian_visit: dg.Nothing,  # type: ignore[valid-type]  # noqa: ARG001 — Dagster dep marker, runtime sentinel
) -> dg.Output[dict[str, Any]]:
    """Scan unpromoted :Claim nodes in the partition's silo and promote eligible ones."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int]:
        from context_service.custodian.fact_promotion import evaluate_claim_for_fact
        from context_service.db.queries import PROMOTE_CLAIM_TO_FACT

        driver = await memgraph.driver()
        from context_service.stores import MemgraphClient

        client = MemgraphClient(driver)

        rows = await client.execute_query(
            _SCAN_UNPROMOTED_CLAIMS,
            {"silo_id": silo_id, "batch_size": _BATCH_SIZE},
        )
        claims_scanned = len(rows)
        claims_promoted = 0

        if not rows:
            return claims_scanned, claims_promoted

        claim_ids: list[str] = [str(r["id"]) for r in rows]
        props_by_id: dict[str, dict[str, Any]] = {str(r["id"]): dict(r["props"]) for r in rows}

        # Batch RTT 1: evidence counts for all claims.
        evidence_count_by_id: dict[str, int] = {}
        count_rows = await client.execute_query(
            _BATCH_COUNT_EVIDENCE,
            {"claim_ids": claim_ids, "silo_id": silo_id},
        )
        for cr in count_rows:
            evidence_count_by_id[str(cr["cid"])] = int(cr["cnt"])

        # Batch RTT 2: corroborations for all claims.
        corroborations_by_id: dict[str, list[dict[str, Any]]] = {cid: [] for cid in claim_ids}
        corr_rows = await client.execute_query(
            _BATCH_FETCH_CORROBORATIONS,
            {"claim_ids": claim_ids, "silo_id": silo_id},
        )
        for cr in corr_rows:
            corroborations_by_id[str(cr["cid"])].append(dict(cr["props"]))

        for claim_id in claim_ids:
            claim_props: dict[str, Any] = props_by_id[claim_id]
            evidence_count: int = evidence_count_by_id.get(claim_id, 0)
            corroborations: list[dict[str, Any]] = corroborations_by_id.get(claim_id, [])

            decision = evaluate_claim_for_fact(claim_props, evidence_count, corroborations)
            if not decision.should_promote:
                continue

            rule_value: str = decision.rule.value if decision.rule is not None else ""
            fact_id = str(uuid.uuid4())
            await client.execute_write(
                PROMOTE_CLAIM_TO_FACT,
                {
                    "claim_id": claim_id,
                    "silo_id": silo_id,
                    "rule": rule_value,
                    "fact_id": fact_id,
                },
            )
            claims_promoted += 1
            context.log.info(f"promoted claim {claim_id} -> fact {fact_id} via {rule_value}")

        return claims_scanned, claims_promoted

    scanned, promoted = _run_async(_run())
    duration_s = time.monotonic() - t0
    context.log.info(
        f"silo {silo_id}: scanned={scanned} promoted={promoted} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "claims_scanned": scanned,
            "claims_promoted": promoted,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "claims_scanned": dg.MetadataValue.int(scanned),
            "claims_promoted": dg.MetadataValue.int(promoted),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
