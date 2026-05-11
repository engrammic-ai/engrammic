"""Dagster sensor: trigger belief merge when overlapping beliefs exist for a subject."""

from __future__ import annotations

from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource
from context_service.pipelines.utils import run_async

# Query beliefs grouped by subject to find silos with overlap candidates.
# Returns one row per silo that has at least two active beliefs sharing a subject token.
_LIST_SILOS_WITH_OVERLAP_CANDIDATES = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.status IS NULL OR b.status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH b.silo_id AS silo_id, subject, count(b) AS belief_count
WHERE belief_count >= 2
RETURN silo_id, subject, belief_count
ORDER BY belief_count DESC
LIMIT 50
"""

_LIST_ACTIVE_SILOS = """
MATCH (b:Belief)
RETURN DISTINCT b.silo_id AS silo_id
"""


@dg.sensor(
    name="belief_merge_sensor",
    asset_selection=dg.AssetSelection.assets("belief_merge"),
    minimum_interval_seconds=600,
    description=(
        "Polls for silos that contain overlapping :Belief nodes covering the same "
        "subject. Triggers a belief merge run per (silo_id, subject) pair."
    ),
)
def belief_merge_sensor(
    context,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for overlapping beliefs and request merge runs for qualifying pairs.

    Deduplication is handled entirely by run_key — no cursor tracking needed.
    Dagster guarantees that a RunRequest with a given run_key will not launch a
    new run if a run with that key already exists (succeeded or in-flight).
    """

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        triggers: list[dict[str, Any]] = []
        for silo_id in silo_ids:
            rows = await client.execute_query(
                _LIST_SILOS_WITH_OVERLAP_CANDIDATES,
                {"silo_id": silo_id},
            )
            for row in rows:
                triggers.append(
                    {
                        "silo_id": silo_id,
                        "subject": str(row["subject"]),
                        "belief_count": int(row["belief_count"]),
                    }
                )

        return triggers

    triggers = run_async(_poll())
    if not triggers:
        return dg.SensorResult(run_requests=[])

    run_requests: list[dg.RunRequest] = []
    for t in triggers:
        silo_id: str = t["silo_id"]
        subject: str = t["subject"]
        belief_count: int = t["belief_count"]
        run_requests.append(
            dg.RunRequest(
                run_key=f"belief_merge:{silo_id}:{subject}",
                partition_key=silo_id,
                tags={
                    "dagster/concurrency_key": silo_id,
                    "subject": subject,
                },
            )
        )
        context.log.info(
            f"triggering belief merge silo={silo_id} "
            f"subject={subject!r} belief_count={belief_count}"
        )

    return dg.SensorResult(run_requests=run_requests)
