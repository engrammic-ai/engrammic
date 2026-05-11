"""Groundskeeper nightly GC Dagster job.

Runs memory garbage collection across all active silos, deleting Memory-layer
nodes (Passage, Utterance, Event) that have exceeded their hard_delete_days
threshold per decay class.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
from dagster import OpExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.resources import MemgraphResource

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 100
"""


@dg.op(required_resource_keys={"memgraph"})
def groundskeeper_gc_op(context: OpExecutionContext) -> dict[str, Any]:
    """Run Memory GC for all active silos."""
    from context_service.custodian.identities.groundskeeper import GroundskeeperIdentity

    settings = get_settings()
    decay_config: dict[str, dict[str, object]] = {
        k: {"half_life_days": v.half_life_days, "hard_delete_days": v.hard_delete_days}
        for k, v in settings.identities.groundskeeper.decay_classes.items()
    }

    memgraph: MemgraphResource = context.resources.memgraph

    async def _run() -> dict[str, Any]:
        store = await memgraph.store()
        rows = await store.execute_query(_LIST_ACTIVE_SILOS, {})
        silos = [str(r["silo_id"]) for r in rows if r.get("silo_id")]

        total_deleted = 0
        for silo_id in silos:
            gk = GroundskeeperIdentity(store=store, silo_id=silo_id, decay_config=decay_config)
            result = await gk.run_gc()
            deleted = result["deleted"]
            assert isinstance(deleted, int)
            total_deleted += deleted
            context.log.info(f"groundskeeper.gc: silo={silo_id} deleted={deleted}")

        return {"total_deleted": total_deleted, "silos_processed": len(silos)}

    return asyncio.run(_run())


@dg.job(name="groundskeeper_nightly")
def groundskeeper_nightly() -> None:
    """Nightly memory GC job: delete expired Memory-layer nodes across all silos."""
    groundskeeper_gc_op()
