"""Dagster asset: cascade_review — process revision-cascade-pending beliefs per silo."""

import contextlib
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import EmbeddingResource, LLMResource, MemgraphResource
from context_service.pipelines.utils import run_async


@dg.asset(
    name="cascade_review",
    partitions_def=silo_partitions,
    description=(
        "Process :Belief nodes flagged with revision_cascade_pending = true. "
        "For each pending belief: checks if revision is needed and revises if so, "
        "then clears the cascade flag. Triggered by cascade_review_sensor."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=5.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "cascade_review"},
)
def cascade_review_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
    embedding: EmbeddingResource,
) -> dg.Output[dict[str, Any]]:
    """Review and process all cascade-pending beliefs for the silo partition."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, int]:
        from context_service.engine.revision import (
            check_belief_revision,
            clear_cascade_pending,
            get_cascade_pending,
            revise_belief,
        )

        store = await memgraph.store()
        llm_client = llm.get_client()
        embedding_client = embedding.get_client()

        pending = await get_cascade_pending(store, silo_id)
        if not pending:
            context.log.info(f"cascade_review silo={silo_id} no pending beliefs")
            return {"processed": 0, "revised": 0, "skipped": 0, "errors": 0}

        processed = 0
        revised = 0
        skipped = 0
        errors = 0

        for belief_row in pending:
            belief_id: str = str(belief_row["belief_id"])
            try:
                result = await check_belief_revision(store, belief_id, silo_id, embedding_client)
                if result.needs_revision:
                    await revise_belief(
                        store, belief_id, silo_id, llm_client, embedding_client,
                        cosine_distance=result.cosine_distance,
                    )
                    revised += 1
                    context.log.info(
                        f"cascade_review silo={silo_id} belief={belief_id} revised "
                        f"distance={result.cosine_distance:.4f}"
                    )
                else:
                    skipped += 1
                    context.log.debug(
                        f"cascade_review silo={silo_id} belief={belief_id} no_revision "
                        f"reason={result.reason}"
                    )

                await clear_cascade_pending(store, belief_id, silo_id)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                errors += 1
                context.log.warning(
                    f"cascade_review silo={silo_id} belief={belief_id} error={exc!r}"
                )
                # Still attempt to clear the flag so we don't reprocess indefinitely
                # on transient failures — sensor will re-flag if drift is still present.
                with contextlib.suppress(Exception):
                    await clear_cascade_pending(store, belief_id, silo_id)

        return {"processed": processed, "revised": revised, "skipped": skipped, "errors": errors}

    counts = run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"cascade_review silo={silo_id} processed={counts['processed']} "
        f"revised={counts['revised']} skipped={counts['skipped']} "
        f"errors={counts['errors']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "processed": counts["processed"],
            "revised": counts["revised"],
            "skipped": counts["skipped"],
            "errors": counts["errors"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "processed": dg.MetadataValue.int(counts["processed"]),
            "revised": dg.MetadataValue.int(counts["revised"]),
            "skipped": dg.MetadataValue.int(counts["skipped"]),
            "errors": dg.MetadataValue.int(counts["errors"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
