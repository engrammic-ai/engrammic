"""Dagster asset: proposal_detection — create ProposedBelief for weak synthesis candidates."""

import asyncio
import concurrent.futures
import json
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
    deps=["clustering"],
    description="Detect weak synthesis candidates and create ProposedBelief nodes.",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "proposal_detection"},
)
def proposal_detection(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Create ProposedBelief nodes for clusters in the proposal confidence range."""
    silo_id: str = context.partition_key

    async def _run() -> list[str]:
        from context_service.config.settings import get_settings
        from context_service.custodian.proposal_worker import run_proposal_detection
        from context_service.models.silo import SiloConfig

        settings = get_settings()
        graph_store = await memgraph.store()

        # Fetch per-silo config from the Silo node
        rows: list[dict[str, Any]] = await graph_store.execute_query(
            "MATCH (s:Silo {id: $silo_id}) RETURN s.silo_config AS silo_config",
            {"silo_id": silo_id},
        )

        silo_config: SiloConfig
        if rows and rows[0].get("silo_config"):
            raw = rows[0]["silo_config"]
            try:
                data: dict[str, Any] = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError:
                context.log.warning(
                    f"proposal_detection: malformed silo config for {silo_id}, using defaults"
                )
                data = {}
            silo_config = SiloConfig.from_metadata_dict(data)
        else:
            silo_config = SiloConfig()

        resolved = silo_config.resolve(settings)
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
