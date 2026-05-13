"""Dagster sensor: trigger synthesis when pending clusters exceed threshold."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg

from context_service.config.settings import get_settings
from context_service.pipelines.resources import MemgraphResource

_PENDING_CLUSTERS_BY_SILO = """
MATCH (c:Cluster)
OPTIONAL MATCH (c)<-[:COVERS]-(b:Belief)
WITH c, b
WHERE b IS NULL
WITH c.silo_id AS silo_id, count(c) AS pending
WHERE pending >= $threshold
RETURN silo_id, pending
"""


@dg.sensor(
    name="synthesizer_threshold_sensor",
    asset_selection=dg.AssetSelection.assets("belief_synthesis"),
    minimum_interval_seconds=300,
    description=(
        "Triggers synthesis when uncovered clusters per silo exceed "
        "identities.synthesizer.threshold_pending_nodes."
    ),
)
def synthesizer_threshold_sensor(
    context,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for silos with too many uncovered clusters and request synthesis runs."""
    settings = get_settings()
    if not settings.identities.synthesizer.enabled:
        context.log.info("synthesizer_threshold_sensor: disabled, skipping")
        return dg.SensorResult(run_requests=[])

    threshold = settings.identities.synthesizer.threshold_pending_nodes

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(_PENDING_CLUSTERS_BY_SILO, {"threshold": threshold})
        return [
            {"silo_id": str(r["silo_id"]), "pending": int(r["pending"])}
            for r in rows
            if r.get("silo_id")
        ]

    candidates = asyncio.run(_poll())

    if not candidates:
        return dg.SensorResult(run_requests=[])

    run_requests: list[dg.RunRequest] = []
    for c in candidates:
        silo_id: str = c["silo_id"]
        pending: int = c["pending"]
        context.log.info(f"synthesizer_threshold_sensor: silo={silo_id} pending_clusters={pending}")
        run_requests.append(
            dg.RunRequest(
                run_key=f"synthesizer:{silo_id}:{context.cursor or 'init'}",
                partition_key=silo_id,
                run_config={"ops": {"synthesizer_sweep_op": {"config": {"silo_id": silo_id}}}},
                tags={"dagster/concurrency_key": silo_id},
            )
        )

    return dg.SensorResult(run_requests=run_requests)
