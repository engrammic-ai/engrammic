"""Dagster asset: proposal_detection — create ProposedBelief for weak synthesis candidates."""

from __future__ import annotations

import asyncio
import concurrent.futures
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
    name="proposal_detection",
    partitions_def=silo_partitions,
    ins={"clustering": dg.AssetIn("clustering")},
    description="Detect weak synthesis candidates and create ProposedBelief nodes.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "proposal_detection"},
)
def proposal_detection(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    clustering: dg.Nothing,  # type: ignore[valid-type]  # noqa: ARG001
) -> dg.Output[dict[str, Any]]:
    """Create ProposedBelief nodes for clusters in the proposal confidence range."""
    silo_id: str = context.partition_key

    async def _run() -> list[str]:
        from context_service.config.settings import get_settings
        from context_service.custodian.proposal_worker import run_proposal_detection
        from context_service.models.silo import SiloConfig

        settings = get_settings()
        graph_store = await memgraph.store()

        resolved = SiloConfig().resolve(settings)
        return await run_proposal_detection(graph_store, silo_id, resolved)

    created_ids = _run_async(_run())

    context.log.info(f"Created {len(created_ids)} ProposedBelief nodes for silo {silo_id}")

    return dg.Output(
        value={"silo_id": silo_id, "proposals_created": len(created_ids)},
        metadata={
            "proposals_created": len(created_ids),
            "proposal_ids": created_ids[:10],
        },
    )
