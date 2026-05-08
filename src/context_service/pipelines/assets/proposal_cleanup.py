"""Dagster asset: proposal_cleanup — delete expired ProposedBelief nodes."""

import asyncio
import concurrent.futures
from datetime import UTC, datetime
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


@dg.asset(
    name="proposal_cleanup",
    partitions_def=silo_partitions,
    description="Delete expired ProposedBelief nodes.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
)
def proposal_cleanup(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Delete ProposedBelief nodes past their expires_at timestamp."""
    silo_id: str = context.partition_key

    async def _run() -> int:
        from context_service.db.queries import DELETE_EXPIRED_PROPOSALS

        graph_store = await memgraph.store()
        now = datetime.now(UTC).isoformat()

        result = await graph_store.execute_query(
            DELETE_EXPIRED_PROPOSALS,
            {"silo_id": silo_id, "now": now},
        )
        return int(result[0]["deleted_count"]) if result else 0

    deleted_count = _run_async(_run())

    context.log.info(f"Deleted {deleted_count} expired proposals for silo {silo_id}")

    return dg.Output(
        value={"silo_id": silo_id, "deleted_count": deleted_count},
        metadata={"deleted_count": deleted_count},
    )
