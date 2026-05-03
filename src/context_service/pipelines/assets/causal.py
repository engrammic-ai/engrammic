"""Dagster asset: causal_transitivity — infer transitive CAUSES edges per silo.

Transitive invalidation helper lives in engine/causal_invalidation.py so it
can be imported without pulling in the Dagster runtime.
"""

import asyncio
import concurrent.futures
import time
import uuid
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async_int(coro: Any) -> int:
    """Run an int-returning coroutine, handling nested event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result: int = asyncio.run(coro)
        return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(asyncio.run, coro).result(timeout=300)
        return result


_SCAN_CAUSES_CHAINS = """
MATCH path = (a)-[:CAUSES*2..{depth}]->(c)
WHERE a.silo_id = $silo_id
  AND a <> c
  AND ALL(n IN nodes(path) WHERE n.silo_id = $silo_id)
  AND NOT EXISTS((a)-[:CAUSES {{inferred: true}}]->(c))
RETURN a.id AS source_id, c.id AS target_id, relationships(path) AS edges
SKIP $skip
LIMIT $batch_size
"""

_FIND_DERIVED_EDGES = """
MATCH (r:CAUSES {silo_id: $silo_id})
WHERE $superseded_edge_id IN r.inferred_from_edge_ids
  AND r.inferred = true
RETURN r.id AS derived_edge_id
"""

_TOMBSTONE_DERIVED_EDGE = """
MATCH ()-[r:CAUSES {id: $edge_id, silo_id: $silo_id}]->()
SET r.invalidated = true,
    r.invalidated_at = $invalidated_at,
    r.invalidation_reason = $reason
"""

_UPSERT_INFERRED_CAUSES = """
MATCH (a {{id: $source_id, silo_id: $silo_id}})
MATCH (c {{id: $target_id, silo_id: $silo_id}})
MERGE (a)-[r:CAUSES {{silo_id: $silo_id, inferred: true}}]->(c)
ON CREATE SET
    r.id = $edge_id,
    r.consensus_confidence = $confidence,
    r.extraction_confidence = null,
    r.inferred_from_edge_ids = $inferred_from_edge_ids,
    r.depth = $depth,
    r.created_at = $created_at
ON MATCH SET
    r.consensus_confidence = $confidence,
    r.inferred_from_edge_ids = $inferred_from_edge_ids,
    r.depth = $depth,
    r.updated_at = $created_at
RETURN r.id AS created_id
"""


def _compute_confidence(edge_confidences: list[tuple[str, float]], formula: str) -> float:
    """Compute chain confidence from per-hop confidences.

    Deduplicates by edge ID before applying the formula so that repeated source
    edges in a diamond path don't double-count.

    Args:
        edge_confidences: List of (edge_id, confidence) tuples.
        formula: One of "minimum" or "geometric_mean".
    """
    if not edge_confidences:
        return 0.0

    # Source-dedup by edge ID, not value.
    seen: set[str] = set()
    unique: list[float] = []
    for edge_id, conf in edge_confidences:
        if edge_id not in seen:
            seen.add(edge_id)
            unique.append(conf)

    if formula == "minimum":
        return min(unique)

    if formula == "geometric_mean":
        product = 1.0
        for c in unique:
            product *= c
        return float(product ** (1.0 / len(unique)))

    # Default: multiplicative.
    result = 1.0
    for c in unique:
        result *= c
    return result


@dg.asset(
    name="causal_transitivity",
    partitions_def=silo_partitions,
    ins={"claim_to_fact_promotion": dg.AssetIn("claim_to_fact_promotion")},
    description="Infer transitive CAUSES edges up to max_transitivity_depth hops per silo.",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "causal_transitivity"},
)
def causal_transitivity(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    claim_to_fact_promotion: dg.Nothing,  # type: ignore[valid-type]  # noqa: ARG001 — Dagster dep marker, runtime sentinel
) -> dg.Output[dict[str, Any]]:
    """Traverse CAUSES chains and materialise inferred transitive edges for the silo partition."""
    settings = get_settings()
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    if not settings.causal.inference_enabled:
        context.log.info(f"silo={silo_id} causal inference disabled — skipping")
        return dg.Output(
            value={"silo_id": silo_id, "edges_created": 0, "skipped": True, "duration_s": 0.0},
            metadata={
                "silo_id": dg.MetadataValue.text(silo_id),
                "edges_created": dg.MetadataValue.int(0),
                "skipped": dg.MetadataValue.bool(True),
            },
        )

    depth = settings.causal.max_transitivity_depth
    min_confidence = settings.causal.min_inferred_confidence
    formula = settings.causal.confidence_formula
    batch_size = settings.causal.transitivity_batch_size

    # Build the query with the depth literal substituted (not a parameter; Cypher
    # variable-length patterns require literal bounds).
    query = _SCAN_CAUSES_CHAINS.format(depth=depth)

    async def _run() -> int:
        from datetime import UTC, datetime

        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        edges_created = 0
        skip = 0

        while True:
            rows = await client.execute_query(
                query,
                {"silo_id": silo_id, "skip": skip, "batch_size": batch_size},
            )
            if not rows:
                break

            for row in rows:
                source_id: str = str(row["source_id"])
                target_id: str = str(row["target_id"])
                edges: list[Any] = list(row["edges"])

                hop_confidences: list[tuple[str, float]] = []
                edge_ids: list[str] = []
                for edge in edges:
                    props = dict(edge) if not isinstance(edge, dict) else edge
                    edge_id = str(props.get("id", ""))
                    if edge_id:
                        edge_ids.append(edge_id)
                    raw_conf = props.get("consensus_confidence") or props.get(
                        "extraction_confidence"
                    )
                    if raw_conf is not None and edge_id:
                        hop_confidences.append((edge_id, float(raw_conf)))

                # If no confidence values are recorded on the hops, use a
                # conservative default of 1.0 per hop so the chain isn't silently
                # skipped — callers control the floor via min_inferred_confidence.
                if not hop_confidences:
                    hop_confidences = [(str(i), 1.0) for i in range(len(edges))]

                confidence = _compute_confidence(hop_confidences, formula)
                if confidence < min_confidence:
                    continue

                hop_count = len(edges)
                new_edge_id = str(uuid.uuid4())
                now = datetime.now(UTC).isoformat()

                await client.execute_write(
                    _UPSERT_INFERRED_CAUSES,
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "silo_id": silo_id,
                        "edge_id": new_edge_id,
                        "confidence": confidence,
                        "inferred_from_edge_ids": edge_ids,
                        "depth": hop_count,
                        "created_at": now,
                    },
                )
                edges_created += 1

            skip += batch_size
            # If the batch was smaller than batch_size we've exhausted results.
            if len(rows) < batch_size:
                break

        return edges_created

    edges_created: int = _run_async_int(_run())
    duration_s = time.monotonic() - t0
    context.log.info(
        f"silo={silo_id} edges_created={edges_created} depth={depth} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "edges_created": edges_created,
            "depth": depth,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "edges_created": dg.MetadataValue.int(edges_created),
            "depth": dg.MetadataValue.int(depth),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
