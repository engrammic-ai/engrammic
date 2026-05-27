"""Dagster asset: batch deduplicate overlapping :Belief nodes by merging them."""

import math
import time
from itertools import combinations
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.pipelines.utils import run_async

_FETCH_BELIEFS_WITH_EMBEDDINGS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE (b.status IS NULL OR b.status <> 'stale')
  AND b.centroid_embedding IS NOT NULL
RETURN b.id AS belief_id, b.content AS content, b.centroid_embedding AS embedding,
       b.confidence AS confidence, b.fact_ids AS fact_ids
"""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _find_overlapping_pairs(
    beliefs: list[dict[str, Any]],
    threshold: float,
    max_pairs: int,
) -> list[tuple[str, str, float]]:
    """Return (belief1_id, belief2_id, similarity) for pairs above threshold."""
    pairs: list[tuple[str, str, float]] = []
    for b1, b2 in combinations(beliefs, 2):
        sim = _cosine_similarity(b1["embedding"], b2["embedding"])
        if sim >= threshold:
            pairs.append((str(b1["belief_id"]), str(b2["belief_id"]), sim))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:max_pairs]


@dg.asset(
    name="belief_merge",
    partitions_def=silo_partitions,
    deps=["belief_synthesis"],
    description=("Batch detect and merge overlapping :Belief nodes using embedding similarity."),
    retry_policy=dg.RetryPolicy(max_retries=1, delay=10.0),
    tags={"dagster/concurrency_key": "belief_merge"},
)
def belief_merge_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Batch merge overlapping beliefs for all subjects in a silo."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.engine.synthesis import merge_beliefs
        from context_service.stores import MemgraphClient

        settings = get_settings()
        threshold = settings.identities.synthesizer.belief_merge_similarity_threshold
        max_pairs = settings.identities.synthesizer.belief_merge_max_pairs

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()
        llm_client = llm.get_client()

        rows = await client.execute_query(
            _FETCH_BELIEFS_WITH_EMBEDDINGS,
            {"silo_id": silo_id},
        )

        beliefs = [
            {
                "belief_id": str(r["belief_id"]),
                "content": str(r["content"]),
                "embedding": list(r["embedding"]),
                "confidence": float(r["confidence"]) if r.get("confidence") is not None else 1.0,
                "fact_ids": list(r["fact_ids"]) if r.get("fact_ids") else [],
            }
            for r in rows
            if r.get("embedding")
        ]

        if len(beliefs) < 2:
            context.log.info(
                f"belief_merge: fewer than 2 beliefs with embeddings for silo={silo_id}"
            )
            return {"merged_count": 0, "skipped_count": 0, "total": 0, "merged_ids": []}

        pairs = _find_overlapping_pairs(beliefs, threshold, max_pairs)

        if not pairs:
            context.log.info(
                f"belief_merge: no overlapping pairs above threshold={threshold} for silo={silo_id}"
            )
            return {"merged_count": 0, "skipped_count": 0, "total": 0, "merged_ids": []}

        context.log.info(
            f"belief_merge: processing {len(pairs)} overlapping pairs for silo={silo_id}"
        )

        beliefs_by_id = {b["belief_id"]: b for b in beliefs}

        merged_count = 0
        skipped_count = 0
        merged_ids: list[str] = []
        merged_set: set[str] = set()

        for belief1_id, belief2_id, similarity in pairs:
            if belief1_id in merged_set or belief2_id in merged_set:
                skipped_count += 1
                continue
            try:
                source_beliefs = [beliefs_by_id[belief1_id], beliefs_by_id[belief2_id]]
                merged_id = await merge_beliefs(store, silo_id, source_beliefs, llm_client)
                merged_ids.append(merged_id)
                merged_set.add(belief1_id)
                merged_set.add(belief2_id)
                merged_count += 1
                context.log.info(
                    f"beliefs_merged pair=({belief1_id}, {belief2_id}) similarity={similarity:.3f} "
                    f"merged_belief={merged_id}"
                )
            except Exception as e:
                context.log.error(
                    f"belief_merge failed pair=({belief1_id}, {belief2_id}) error={e}"
                )
                skipped_count += 1

        return {
            "merged_count": merged_count,
            "skipped_count": skipped_count,
            "total": len(pairs),
            "merged_ids": merged_ids,
        }

    result = run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"belief_merge_batch complete silo={silo_id} "
        f"merged={result['merged_count']} skipped={result['skipped_count']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "merged_count": result["merged_count"],
            "skipped_count": result["skipped_count"],
            "total": result["total"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "merged_count": dg.MetadataValue.int(result["merged_count"]),
            "skipped_count": dg.MetadataValue.int(result["skipped_count"]),
            "total": dg.MetadataValue.int(result["total"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
