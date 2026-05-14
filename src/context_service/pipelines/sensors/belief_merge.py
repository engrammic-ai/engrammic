"""Dagster sensor: trigger belief merge batch when overlapping beliefs exist."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource
from context_service.pipelines.utils import run_async

_LIST_SILOS_WITH_PENDING_MERGES = """
MATCH (b:Belief)
WHERE b.status IS NULL OR b.status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH b.silo_id AS silo_id, subject, count(b) AS belief_count
WHERE belief_count >= 2
RETURN DISTINCT silo_id, count(subject) AS pending_subjects
"""


@dg.sensor(
    name="belief_merge_sensor",
    asset_selection=dg.AssetSelection.assets("belief_merge"),
    minimum_interval_seconds=600,
    description=(
        "Polls for silos with overlapping :Belief nodes. Triggers one batch "
        "merge run per silo."
    ),
)
def belief_merge_sensor(
    context,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for silos with overlapping beliefs and trigger one batch run per silo."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        rows = await client.execute_query(_LIST_SILOS_WITH_PENDING_MERGES, {})
        return [
            {"silo_id": str(r["silo_id"]), "pending_subjects": int(r["pending_subjects"])}
            for r in rows
            if r.get("silo_id") and r.get("pending_subjects", 0) > 0
        ]

    silos_with_pending = run_async(_poll())
    if not silos_with_pending:
        return dg.SensorResult(run_requests=[])

    run_requests: list[dg.RunRequest] = []
    now = datetime.now(UTC).isoformat()

    for entry in silos_with_pending:
        silo_id: str = entry["silo_id"]
        pending_subjects: int = entry["pending_subjects"]
        run_key = f"belief_merge_batch:{silo_id}:{now}"

        run_requests.append(
            dg.RunRequest(
                run_key=run_key,
                partition_key=silo_id,
                tags={"dagster/concurrency_key": f"belief_merge:{silo_id}"},
            )
        )
        context.log.info(
            f"triggering belief merge batch silo={silo_id} "
            f"pending_subjects={pending_subjects}"
        )

    return dg.SensorResult(run_requests=run_requests)
