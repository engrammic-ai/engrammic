"""Dagster sensor: trigger belief synthesis when cluster density threshold is met."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import dagster as dg

from context_service.engine.synthesis import _get_min_facts_for_belief
from context_service.pipelines.resources import MemgraphResource
from context_service.utils.json import JSONDecodeError, loads

_LIST_ACTIVE_SILOS_WITH_PENDING_CLUSTERS = """
MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster)
WITH c, count(f) AS fact_count
WHERE fact_count >= $min_facts
OPTIONAL MATCH (c)<-[:SYNTHESIZED_FROM]-(b:Belief {silo_id: c.silo_id})
WITH c, fact_count, b
WHERE b IS NULL
RETURN DISTINCT c.silo_id AS silo_id, count(c) AS pending_count
"""


def _parse_cursor(cursor: str | None) -> dict[str, str]:
    if not cursor:
        return {}
    try:
        data: dict[str, str] = loads(cursor)
        return data
    except JSONDecodeError:
        return {}


@dg.sensor(
    name="belief_synthesis_sensor",
    asset_selection=dg.AssetSelection.assets("belief_synthesis"),
    minimum_interval_seconds=120,
    description=(
        "Triggers belief synthesis batch job per silo when clusters meet the "
        "density threshold and lack a covering :Belief node."
    ),
)
def belief_synthesis_sensor(
    context,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for silos with pending clusters and trigger one batch run per silo."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        rows = await client.execute_query(
            _LIST_ACTIVE_SILOS_WITH_PENDING_CLUSTERS,
            {"min_facts": _get_min_facts_for_belief()},
        )
        return [
            {"silo_id": str(r["silo_id"]), "pending_count": int(r["pending_count"])}
            for r in rows
            if r.get("silo_id") and r.get("pending_count", 0) > 0
        ]

    silos_with_pending = asyncio.run(_poll())
    if not silos_with_pending:
        return dg.SensorResult(run_requests=[], cursor=context.cursor or "{}")

    cursor_data = _parse_cursor(context.cursor)
    run_requests: list[dg.RunRequest] = []
    now = datetime.now(UTC).isoformat()

    for entry in silos_with_pending:
        silo_id: str = entry["silo_id"]
        pending_count: int = entry["pending_count"]
        last_run = cursor_data.get(silo_id)
        run_key = f"belief_synthesis_batch:{silo_id}:{now}"

        run_requests.append(
            dg.RunRequest(
                run_key=run_key,
                partition_key=silo_id,
                tags={"dagster/concurrency_key": f"belief_synthesis:{silo_id}"},
            )
        )
        cursor_data[silo_id] = now
        context.log.info(
            f"triggering belief synthesis batch silo={silo_id} "
            f"pending_clusters={pending_count} last_run={last_run}"
        )

    return dg.SensorResult(
        run_requests=run_requests,
        cursor="{}" if not cursor_data else str(cursor_data).replace("'", '"'),
    )
