"""Dagster asset: weak link promotion, pruning, and demotion.

Runs after heat assets. Promotes high-signal speculative edges, prunes old
unused ones, demotes promoted edges whose endpoints were superseded.
"""

import asyncio
import concurrent.futures
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


PROMOTE_CYPHER = """
MATCH (a)-[:SOURCE_OF]->(w:WeakLink)-[:TARGETS]->(b)
WHERE w.speculative = true
  AND w.silo_id = $silo_id
  AND w.weight >= $min_weight
  AND w.edge_heat >= $min_edge_heat
  AND ($require_facts = false OR (a:Fact AND b:Fact))
SET w.speculative = false,
    w.promoted_at = datetime(),
    w.promoted_by = 'custodian'
RETURN count(w) AS promoted
"""

PRUNE_CYPHER = """
MATCH (a)-[s:SOURCE_OF]->(w:WeakLink)-[t:TARGETS]->(b)
WHERE w.speculative = true
  AND w.silo_id = $silo_id
  AND w.created_at < datetime() - duration({days: $max_age_days})
  AND w.edge_heat < $min_edge_heat
DELETE s, t, w
RETURN count(w) AS pruned
"""

DEMOTE_SUPERSEDED_CYPHER = """
MATCH (a)-[:SOURCE_OF]->(w:WeakLink)-[:TARGETS]->(b)
WHERE w.speculative = false
  AND w.silo_id = $silo_id
  AND (a.superseded = true OR b.superseded = true)
SET w.speculative = true,
    w.demoted_at = datetime(),
    w.demoted_reason = 'endpoint_superseded'
RETURN count(w) AS demoted
"""


@dg.asset(
    name="weak_link_review",
    partitions_def=silo_partitions,
    deps=["heat", "edge_heat"],
    description="Promote high-signal weak links, prune unused ones, demote stale promoted links",
)
def weak_link_review_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Review weak links: promote, prune, demote."""
    silo_id = context.partition_key
    settings = get_settings()
    wl = settings.weak_links

    async def _run() -> dict[str, Any]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg = MemgraphClient(driver)

        promote_result = await mg.execute_write(
            PROMOTE_CYPHER,
            {
                "silo_id": silo_id,
                "min_weight": wl.promotion_min_weight,
                "min_edge_heat": wl.promotion_min_edge_heat,
                "require_facts": wl.promotion_require_fact_endpoints,
            },
        )
        promoted = promote_result[0]["promoted"] if promote_result else 0

        prune_result = await mg.execute_write(
            PRUNE_CYPHER,
            {
                "silo_id": silo_id,
                "max_age_days": wl.pruning_max_age_days,
                "min_edge_heat": wl.pruning_min_edge_heat,
            },
        )
        pruned = prune_result[0]["pruned"] if prune_result else 0

        demote_result = await mg.execute_write(DEMOTE_SUPERSEDED_CYPHER, {"silo_id": silo_id})
        demoted = demote_result[0]["demoted"] if demote_result else 0

        return {
            "silo_id": silo_id,
            "promoted": promoted,
            "pruned": pruned,
            "demoted": demoted,
        }

    result = _run_async(_run())
    context.log.info(f"Weak link review: {result}")
    return dg.Output(result)
