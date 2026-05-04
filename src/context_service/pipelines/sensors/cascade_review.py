"""Dagster sensor: trigger cascade review when beliefs have revision_cascade_pending set."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource

_LIST_ACTIVE_SILOS = """
MATCH (b:Belief)
WHERE b.silo_id IS NOT NULL
RETURN DISTINCT b.silo_id AS silo_id
"""

_CASCADE_PENDING_LIMIT = 100


@dg.sensor(
    name="cascade_review_sensor",
    asset_selection=dg.AssetSelection.assets("cascade_review"),
    minimum_interval_seconds=180,
    description=(
        "Polls for :Belief nodes with revision_cascade_pending = true per active silo. "
        "Yields a RunRequest for each silo that has pending beliefs."
    ),
)
def cascade_review_sensor(
    context: dg.SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Check for cascade-pending beliefs per silo and trigger review runs."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.engine.revision import get_cascade_pending
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        store = await memgraph.store()

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        triggers: list[dict[str, Any]] = []
        for silo_id in silo_ids:
            pending = await get_cascade_pending(store, silo_id, limit=_CASCADE_PENDING_LIMIT)
            if pending:
                triggers.append({"silo_id": silo_id, "pending_count": len(pending)})

        return triggers

    triggers = asyncio.run(_poll())
    if not triggers:
        return dg.SensorResult(run_requests=[])

    run_requests: list[dg.RunRequest] = []
    for t in triggers:
        silo_id: str = t["silo_id"]
        run_requests.append(
            dg.RunRequest(
                run_key=f"cascade_review:{silo_id}",
                partition_key=silo_id,
                tags={"dagster/concurrency_key": silo_id},
            )
        )
        context.log.info(
            f"triggering cascade_review silo={silo_id} pending={t['pending_count']}"
        )

    return dg.SensorResult(run_requests=run_requests)
