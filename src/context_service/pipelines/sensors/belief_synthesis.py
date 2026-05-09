"""Dagster sensor: trigger belief synthesis when cluster density threshold is met."""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
from dagster import SensorEvaluationContext

from context_service.engine.synthesis import _get_min_facts_for_belief
from context_service.pipelines.resources import MemgraphResource
from context_service.utils.json import JSONDecodeError, dumps, loads

# Query clusters that meet the minimum fact density threshold and
# do not yet have a :Belief synthesised from them.
_LIST_DENSE_CLUSTERS_WITHOUT_BELIEF = """
MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
WITH c, count(f) AS fact_count
WHERE fact_count >= $min_facts
  AND size([(c)<-[:SYNTHESIZED_FROM]-(b:Belief {silo_id: $silo_id}) | b]) = 0
RETURN c.id AS cluster_id, fact_count
ORDER BY fact_count DESC
"""

_LIST_ACTIVE_SILOS = """
MATCH (c:Cluster)
RETURN DISTINCT c.silo_id AS silo_id
"""


def _parse_cursor(cursor: str | None) -> dict[str, list[str]]:
    if not cursor:
        return {}
    try:
        data: dict[str, list[str]] = loads(cursor)
        return data
    except JSONDecodeError:
        return {}


@dg.sensor(
    name="belief_synthesis_sensor",
    asset_selection=dg.AssetSelection.assets("belief_synthesis"),
    minimum_interval_seconds=120,
    description=(
        "Triggers belief synthesis for clusters meeting the density threshold "
        "(belief_density_threshold setting) that lack a covering :Belief node."
    ),
)
def belief_synthesis_sensor(
    context: SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for dense clusters and request synthesis runs for uncovered ones."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        triggers: list[dict[str, Any]] = []
        cursor_data = _parse_cursor(context.cursor)

        for silo_id in silo_ids:
            already_seen: list[str] = cursor_data.get(silo_id, [])
            rows = await client.execute_query(
                _LIST_DENSE_CLUSTERS_WITHOUT_BELIEF,
                {"silo_id": silo_id, "min_facts": _get_min_facts_for_belief()},
            )
            for row in rows:
                cluster_id = str(row["cluster_id"])
                if cluster_id in already_seen:
                    continue
                triggers.append(
                    {
                        "silo_id": silo_id,
                        "cluster_id": cluster_id,
                        "fact_count": int(row["fact_count"]),
                    }
                )

        return triggers

    triggers = asyncio.run(_poll())
    if not triggers:
        return dg.SensorResult(run_requests=[], cursor=context.cursor or "{}")

    cursor_data = _parse_cursor(context.cursor)
    run_requests: list[dg.RunRequest] = []

    for t in triggers:
        silo_id: str = t["silo_id"]
        cluster_id: str = t["cluster_id"]
        run_requests.append(
            dg.RunRequest(
                run_key=f"belief_synthesis:{silo_id}:{cluster_id}",
                partition_key=silo_id,
                tags={
                    "dagster/concurrency_key": silo_id,
                    "cluster_id": cluster_id,
                },
            )
        )
        cursor_data.setdefault(silo_id, [])
        cursor_data[silo_id].append(cluster_id)
        context.log.info(
            f"triggering belief synthesis silo={silo_id} "
            f"cluster={cluster_id} facts={t['fact_count']}"
        )

    return dg.SensorResult(run_requests=run_requests, cursor=dumps(cursor_data))
