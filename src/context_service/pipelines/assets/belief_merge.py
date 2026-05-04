"""Dagster asset: deduplicate overlapping :Belief nodes by merging them."""

import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource
from context_service.pipelines.utils import run_async


@dg.asset(
    name="belief_merge",
    partitions_def=silo_partitions,
    description=(
        "Detect overlapping :Belief nodes for a subject and merge them into a single "
        "canonical belief. Triggered by belief_merge_sensor when overlap is detected."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=5.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "belief_merge"},
)
def belief_merge_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Merge overlapping beliefs for the subject supplied via run tags."""
    silo_id: str = context.partition_key
    subject: str = context.run_tags.get("subject", "")
    if not subject:
        raise ValueError(
            "belief_merge asset requires a 'subject' run tag — "
            "was this triggered without the sensor?"
        )

    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.engine.synthesis import detect_overlapping_beliefs, merge_beliefs

        store = await memgraph.store()
        llm_client = llm.get_client()

        overlaps = await detect_overlapping_beliefs(store, silo_id, subject)
        if not overlaps:
            return {"merged": False, "merged_belief_id": None, "source_count": 0}

        merged_id = await merge_beliefs(store, silo_id, overlaps, llm_client)
        return {"merged": True, "merged_belief_id": merged_id, "source_count": len(overlaps)}

    result = run_async(_run())
    duration_s = time.monotonic() - t0

    merged: bool = result["merged"]
    merged_belief_id: str | None = result["merged_belief_id"]
    source_count: int = result["source_count"]

    if merged:
        context.log.info(
            f"beliefs_merged silo={silo_id} subject={subject!r} "
            f"merged_belief={merged_belief_id} source_count={source_count} "
            f"duration={duration_s:.2f}s"
        )
    else:
        context.log.info(
            f"no_overlap_found silo={silo_id} subject={subject!r} duration={duration_s:.2f}s"
        )

    metadata: dict[str, dg.MetadataValue] = {
        "silo_id": dg.MetadataValue.text(silo_id),
        "subject": dg.MetadataValue.text(subject),
        "merged": dg.MetadataValue.bool(merged),
        "source_count": dg.MetadataValue.int(source_count),
        "duration_s": dg.MetadataValue.float(duration_s),
    }
    if merged_belief_id is not None:
        metadata["merged_belief_id"] = dg.MetadataValue.text(merged_belief_id)

    return dg.Output(
        value={
            "silo_id": silo_id,
            "subject": subject,
            "merged": merged,
            "merged_belief_id": merged_belief_id,
            "source_count": source_count,
            "duration_s": duration_s,
        },
        metadata=metadata,
    )
