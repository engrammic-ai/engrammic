"""Dagster asset: batch synthesise :Belief nodes from corroborating facts (v2).

CITE v2: No clustering. Finds fact groups by (subject, predicate) with sufficient
evidence sources, then calls synthesize_from_facts().
"""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import LLMResource, MemgraphResource

_MAX_CANDIDATES_PER_RUN = 50


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=600)


@dg.asset(
    name="belief_synthesis",
    partitions_def=silo_partitions,
    deps=["claim_to_fact_promotion"],
    description=(
        "Batch synthesise :Belief nodes from corroborating fact groups (v2). "
        "Finds facts sharing (subject, predicate) with sufficient evidence, "
        "then creates ProposedBelief via synthesize_from_facts()."
    ),
    retry_policy=dg.RetryPolicy(max_retries=1, delay=10.0),
    tags={"dagster/concurrency_key": "belief_synthesis"},
)
def belief_synthesis_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    llm: LLMResource,
) -> dg.Output[dict[str, Any]]:
    """Batch synthesise beliefs from corroborating fact groups."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.db import queries as q
        from context_service.sage.transactions import (
            SYNTHESIS_THRESHOLD,
            synthesize_from_facts,
        )

        store = await memgraph.store()
        llm_client = llm.get_client()

        # Find synthesis candidates using v2 query
        candidates = await store.execute_query(
            q.GET_SYNTHESIS_CANDIDATES,
            {
                "silo_id": silo_id,
                "fact_threshold": SYNTHESIS_THRESHOLD,
                "evidence_threshold": 3,
                "limit": _MAX_CANDIDATES_PER_RUN,
            },
        )

        if not candidates:
            context.log.info(f"belief_synthesis: no candidates for silo={silo_id}")
            return {"succeeded": 0, "failed": 0, "total": 0, "belief_ids": []}

        context.log.info(
            f"belief_synthesis: processing {len(candidates)} candidates for silo={silo_id}"
        )

        succeeded = 0
        failed = 0
        belief_ids: list[str] = []

        for candidate in candidates:
            fact_ids = candidate.get("fact_ids", [])
            predicate = candidate.get("predicate", "unknown")

            if len(fact_ids) < SYNTHESIS_THRESHOLD:
                continue

            try:
                result, _events = await synthesize_from_facts(
                    store,
                    fact_ids,
                    silo_id,
                    llm_client,
                    mode="async",
                )

                if result.belief_id:
                    belief_ids.append(result.belief_id)
                    succeeded += 1
                    context.log.info(
                        f"belief_synthesised predicate={predicate} "
                        f"belief={result.belief_id} facts={len(fact_ids)}"
                    )
                else:
                    context.log.debug(
                        f"synthesis_skipped predicate={predicate} "
                        f"timed_out={result.timed_out}"
                    )

            except Exception as e:
                failed += 1
                context.log.error(
                    f"belief_synthesis failed predicate={predicate} error={e}"
                )

        return {
            "succeeded": succeeded,
            "failed": failed,
            "total": len(candidates),
            "belief_ids": belief_ids,
        }

    result = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"belief_synthesis_batch complete silo={silo_id} "
        f"succeeded={result['succeeded']} failed={result['failed']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "succeeded": result["succeeded"],
            "failed": result["failed"],
            "total": result["total"],
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "succeeded": dg.MetadataValue.int(result["succeeded"]),
            "failed": dg.MetadataValue.int(result["failed"]),
            "total": dg.MetadataValue.int(result["total"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )
