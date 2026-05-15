"""Dagster asset: batch deduplicate overlapping :Belief nodes by merging them."""

import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.pipelines.utils import run_async

_LIST_OVERLAP_SUBJECTS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.status IS NULL OR b.status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH subject, count(b) AS belief_count
WHERE belief_count >= 2
RETURN subject, belief_count
ORDER BY belief_count DESC
LIMIT $max_subjects
"""

_MAX_SUBJECTS_PER_RUN = 30


@dg.asset(
    name="belief_merge",
    partitions_def=silo_partitions,
    description=(
        "Batch detect and merge overlapping :Belief nodes. Processes up to 30 "
        "subjects with overlaps per run."
    ),
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
        from context_service.engine.synthesis import detect_overlapping_beliefs, merge_beliefs
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()
        llm_client = llm.get_client()

        rows = await client.execute_query(
            _LIST_OVERLAP_SUBJECTS,
            {"silo_id": silo_id, "max_subjects": _MAX_SUBJECTS_PER_RUN},
        )

        subjects = [
            {"subject": str(r["subject"]), "belief_count": int(r["belief_count"])} for r in rows
        ]

        if not subjects:
            context.log.info(f"belief_merge: no overlapping subjects for silo={silo_id}")
            return {"merged_count": 0, "skipped_count": 0, "total": 0, "merged_ids": []}

        context.log.info(f"belief_merge: processing {len(subjects)} subjects for silo={silo_id}")

        merged_count = 0
        skipped_count = 0
        merged_ids: list[str] = []

        for entry in subjects:
            subject = str(entry["subject"])
            try:
                overlaps = await detect_overlapping_beliefs(store, silo_id, subject)
                if not overlaps:
                    skipped_count += 1
                    continue

                merged_id = await merge_beliefs(store, silo_id, overlaps, llm_client)
                merged_ids.append(merged_id)
                merged_count += 1
                context.log.info(
                    f"beliefs_merged subject={subject!r} merged_belief={merged_id} "
                    f"source_count={len(overlaps)}"
                )
            except Exception as e:
                context.log.error(f"belief_merge failed subject={subject!r} error={e}")
                skipped_count += 1

        return {
            "merged_count": merged_count,
            "skipped_count": skipped_count,
            "total": len(subjects),
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
