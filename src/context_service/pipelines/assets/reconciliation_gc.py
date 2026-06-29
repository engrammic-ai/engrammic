"""Dagster asset: hybrid-storage reconciliation GC.

Runs every 15 minutes. Scans OrphanedChains rows with retry_count > 3 and
attempts to re-reconcile each chain by writing the summary projection to
Memgraph. Rows that succeed are removed from both OrphanedChains and
ReasoningChainSteps (cleanup is handled by compaction; GC only removes the
dead-letter entry). Rows that still fail after re-reconciliation are
permanently archived by deleting the Postgres data.

Also removes ReasoningChainSteps rows that have no corresponding
:ReasoningChain node in Memgraph (dangling Postgres data with no graph
counterpart).
"""

import asyncio
import concurrent.futures
import json
import time
from typing import Any
from uuid import UUID

import dagster as dg
from dagster import AssetExecutionContext
from sqlalchemy import delete, select

from context_service.pipelines.resources import MemgraphResource

_BATCH_LIMIT = 200
_RETRY_THRESHOLD = 3

# Check whether a :ReasoningChain node exists in Memgraph for a given chain_id.
_CHECK_CHAIN_EXISTS = """
MATCH (n:ReasoningChain {id: $chain_id, silo_id: $silo_id})
RETURN n.silo_id AS silo_id,
       n.step_count AS step_count,
       n.first_step AS first_step,
       n.final_step AS final_step,
       n.outcome AS outcome,
       n.all_premise_refs AS all_premise_refs,
       n.produced_by_model AS produced_by_model,
       n.produced_by_agent_id AS produced_by_agent_id,
       n.query_context_hash AS query_context_hash,
       n.status AS status,
       n.source AS source
LIMIT 1
"""

_CHECK_DANGLING_BATCH = """
UNWIND $chain_data AS cd
MATCH (n:ReasoningChain {id: cd.chain_id, silo_id: cd.silo_id})
RETURN n.id AS chain_id
"""


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


async def _reconcile_orphans(
    memgraph: MemgraphResource,
) -> dict[str, int]:
    """Re-reconcile orphaned chains and clean dangling Postgres rows."""
    from context_service.db.postgres import get_session
    from context_service.models.postgres.reasoning import OrphanedChains, ReasoningChainSteps
    from context_service.stores import MemgraphClient

    driver = await memgraph.driver()
    mg_client = MemgraphClient(driver)

    recovered = 0
    archived = 0
    dangling_removed = 0

    # --- Phase 1: retry orphaned chains with retry_count > _RETRY_THRESHOLD ---
    async with get_session() as session:
        stmt = (
            select(
                OrphanedChains.chain_id,
                OrphanedChains.silo_id,
                OrphanedChains.last_error,
            )
            .where(OrphanedChains.retry_count > _RETRY_THRESHOLD)
            .limit(_BATCH_LIMIT)
        )
        rows = (await session.execute(stmt)).all()

    for row in rows:
        chain_id: UUID = row.chain_id
        silo_id: UUID = row.silo_id
        chain_id_str = str(chain_id)
        silo_id_str = str(silo_id)

        # Fetch the stored steps from Postgres so we can rebuild the projection.
        async with get_session() as session:
            steps_stmt = select(ReasoningChainSteps.steps).where(
                ReasoningChainSteps.chain_id == chain_id
            )
            steps_result = await session.execute(steps_stmt)
            steps_data: list[dict[str, Any]] | None = steps_result.scalar_one_or_none()

        if steps_data is None:
            # No steps row — nothing to reconcile, purge the orphan entry.
            async with get_session() as session:
                await session.execute(
                    delete(OrphanedChains).where(OrphanedChains.chain_id == chain_id)
                )
            archived += 1
            continue

        # Derive summary fields from stored steps payload.
        step_count = len(steps_data)
        first_step = json.dumps(steps_data[0]) if steps_data else None
        final_step = json.dumps(steps_data[-1]) if steps_data else None
        all_premise_refs: list[str] = []
        for step in steps_data:
            all_premise_refs.extend(step.get("premise_refs", []))

        final_confidence = steps_data[-1].get("confidence", 0.0) if steps_data else 0.0
        if final_confidence >= 0.8:
            outcome = "success"
        elif final_confidence >= 0.5:
            outcome = "inconclusive"
        else:
            outcome = "failure"

        try:
            await mg_client.execute_write(
                """
                MERGE (n:ReasoningChain {id: $chain_id, silo_id: $silo_id})
                ON CREATE SET
                    n.step_count = $step_count,
                    n.first_step = $first_step,
                    n.final_step = $final_step,
                    n.outcome = $outcome,
                    n.all_premise_refs = $all_premise_refs,
                    n.produced_by_model = $produced_by_model,
                    n.produced_by_agent_id = $produced_by_agent_id,
                    n.status = $status,
                    n.source = $source
                ON MATCH SET
                    n.step_count = $step_count,
                    n.first_step = $first_step,
                    n.final_step = $final_step,
                    n.outcome = $outcome,
                    n.all_premise_refs = $all_premise_refs
                """,
                {
                    "chain_id": chain_id_str,
                    "silo_id": silo_id_str,
                    "step_count": step_count,
                    "first_step": first_step,
                    "final_step": final_step,
                    "outcome": outcome,
                    "all_premise_refs": all_premise_refs,
                    "produced_by_model": steps_data[0].get("produced_by_model", "unknown")
                    if steps_data
                    else "unknown",
                    "produced_by_agent_id": steps_data[0].get("produced_by_agent_id", "unknown")
                    if steps_data
                    else "unknown",
                    "status": "published",
                    "source": "gc_reconciled",
                },
            )
            # Reconciliation succeeded — remove from dead-letter table.
            async with get_session() as session:
                await session.execute(
                    delete(OrphanedChains).where(OrphanedChains.chain_id == chain_id)
                )
            recovered += 1
        except Exception:
            # Still failing — archive: delete both the dead-letter row and the
            # Postgres steps row so the data does not accumulate indefinitely.
            async with get_session() as session:
                await session.execute(
                    delete(OrphanedChains).where(OrphanedChains.chain_id == chain_id)
                )
                await session.execute(
                    delete(ReasoningChainSteps).where(ReasoningChainSteps.chain_id == chain_id)
                )
            archived += 1

    # --- Phase 2: clean dangling ReasoningChainSteps with no Memgraph node ---
    async with get_session() as session:
        dangling_stmt = (
            select(ReasoningChainSteps.chain_id, ReasoningChainSteps.silo_id)
            .outerjoin(
                OrphanedChains,
                ReasoningChainSteps.chain_id == OrphanedChains.chain_id,
            )
            .where(OrphanedChains.chain_id.is_(None))
            .limit(_BATCH_LIMIT)
        )
        dangling_rows = (await session.execute(dangling_stmt)).all()

    if dangling_rows:
        # Pass both chain_id and silo_id for silo-scoped matching
        chain_data = [
            {"chain_id": str(r.chain_id), "silo_id": str(r.silo_id)} for r in dangling_rows
        ]
        mg_present = await mg_client.execute_query(
            _CHECK_DANGLING_BATCH, {"chain_data": chain_data}
        )
        present_set = {r["chain_id"] for r in mg_present}
        truly_dangling = [UUID(cd["chain_id"]) for cd in chain_data if cd["chain_id"] not in present_set]
        if truly_dangling:
            async with get_session() as session:
                await session.execute(
                    delete(ReasoningChainSteps).where(
                        ReasoningChainSteps.chain_id.in_(truly_dangling)
                    )
                )
            dangling_removed = len(truly_dangling)

    return {
        "recovered": recovered,
        "archived": archived,
        "dangling_removed": dangling_removed,
    }


@dg.asset(
    name="reconciliation_gc",
    description=(
        "Hybrid-storage GC: re-reconcile orphaned chains (retry_count > 3) back to "
        "Memgraph; archive permanently failing rows; remove dangling ReasoningChainSteps "
        "that have no corresponding Memgraph node."
    ),
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "reconciliation_gc"},
)
def reconciliation_gc(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Run the hybrid-storage reconciliation GC pass."""
    t0 = time.monotonic()
    result = _run_async(_reconcile_orphans(memgraph))
    duration_s = time.monotonic() - t0

    context.log.info(
        f"reconciliation_gc recovered={result['recovered']} "
        f"archived={result['archived']} "
        f"dangling_removed={result['dangling_removed']} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            **result,
            "duration_s": duration_s,
        },
        metadata={
            "recovered": dg.MetadataValue.int(result["recovered"]),
            "archived": dg.MetadataValue.int(result["archived"]),
            "dangling_removed": dg.MetadataValue.int(result["dangling_removed"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["reconciliation_gc"]
