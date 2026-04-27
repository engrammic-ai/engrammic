"""Dagster asset: batch :Claim -> :Claim:Fact promotion per silo."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource

silo_partitions = dg.DynamicPartitionsDefinition(name="silo_id")

_BATCH_SIZE = 500

_SCAN_UNPROMOTED_CLAIMS = """
MATCH (c:Claim)
WHERE c.silo_id = $silo_id AND NOT c:Fact
RETURN c.id AS id, properties(c) AS props
LIMIT $batch_size
"""

# Count both edge types: extraction emits REFERENCES, assert_claim emits
# DERIVED_FROM. Either signals evidence for promotion.
_COUNT_EVIDENCE = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->()
RETURN count(*) AS cnt
"""

# Corroborating claims = other :Claim nodes that reference (or derive from) the
# same evidence node as this claim.
_FETCH_CORROBORATIONS = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->(ref)
MATCH (other:Claim {silo_id: $silo_id})-[:REFERENCES|DERIVED_FROM]->(ref)
WHERE other.id <> $claim_id
RETURN DISTINCT properties(other) AS props
LIMIT 10
"""


@dg.asset(
    name="claim_to_fact_promotion",
    partitions_def=silo_partitions,
    required_resource_keys={"memgraph"},
    description="Batch-promote :Claim nodes to :Claim:Fact per silo using EAG R1/R2 rules.",
)
def claim_to_fact_promotion(
    context: dg.AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Scan unpromoted :Claim nodes in the partition's silo and promote eligible ones."""
    silo_id: str = context.partition_key

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

        for row in rows:
            claim_id: str = str(row["id"])
            claim_props: dict[str, Any] = dict(row["props"])

            count_rows = await client.execute_query(
                _COUNT_EVIDENCE,
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            evidence_count: int = int(count_rows[0]["cnt"]) if count_rows else 0

            corr_rows = await client.execute_query(
                _FETCH_CORROBORATIONS,
                {"claim_id": claim_id, "silo_id": silo_id},
            )
            corroborations: list[dict[str, Any]] = [dict(r["props"]) for r in corr_rows]

            decision = evaluate_claim_for_fact(claim_props, evidence_count, corroborations)
            if not decision.should_promote:
                continue

            rule_value: str = decision.rule.value if decision.rule is not None else ""
            await client.execute_write(
                PROMOTE_CLAIM_TO_FACT,
                {"claim_id": claim_id, "silo_id": silo_id, "rule": rule_value},
            )
            claims_promoted += 1
            context.log.info(f"promoted claim {claim_id} via {rule_value}")

        return claims_scanned, claims_promoted

    scanned, promoted = asyncio.run(_run())
    context.log.info(f"silo {silo_id}: scanned={scanned} promoted={promoted}")

    return dg.Output(
        value={"silo_id": silo_id, "claims_scanned": scanned, "claims_promoted": promoted},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "claims_scanned": dg.MetadataValue.int(scanned),
            "claims_promoted": dg.MetadataValue.int(promoted),
        },
    )
