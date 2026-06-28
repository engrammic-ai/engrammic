"""Source node cleanup Dagster job.

Deletes orphan Source nodes not linked to any active Claim and older than 7 days.
Catches Source nodes whose Claims were deleted or never promoted.

The inline cleanup in promote() handles the happy path. This job is the safety net.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 100
"""

_CLEANUP_ORPHAN_SOURCES = """
MATCH (s:Source {silo_id: $silo_id})
WHERE NOT (s)<-[:DERIVED_FROM]-()
  AND s.created_at < $cutoff
DETACH DELETE s
RETURN count(s) AS deleted
"""


@dg.op(required_resource_keys={"memgraph"})
def cleanup_orphan_sources(context) -> dict[str, Any]:
    """Delete Source nodes not linked to any Claim and older than 7 days."""
    memgraph = context.resources.memgraph
    cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()

    async def _run() -> dict[str, Any]:
        store = await memgraph.store()
        rows = await store.execute_query(_LIST_ACTIVE_SILOS, {})
        silos = [str(r["silo_id"]) for r in rows if r.get("silo_id")]

        total_deleted = 0
        for silo_id in silos:
            try:
                result = await store.execute_query(
                    _CLEANUP_ORPHAN_SOURCES,
                    {"cutoff": cutoff, "silo_id": silo_id},
                )
                deleted = result[0].get("deleted", 0) if result else 0
                total_deleted += int(deleted)
                if deleted:
                    context.log.info(
                        f"source_cleanup: silo={silo_id} deleted={deleted}"
                    )
            except Exception as e:
                context.log.warning(
                    f"source_cleanup_failed: silo={silo_id} error={e}"
                )

        return {"total_deleted": total_deleted, "silos_processed": len(silos), "cutoff": cutoff}

    return asyncio.run(_run())


@dg.job(name="source_cleanup_job")
def source_cleanup_job() -> None:
    """Delete orphan Source nodes older than 7 days.

    Catches Source nodes whose Claims were deleted or never promoted.
    """
    cleanup_orphan_sources()


@dg.schedule(
    job=source_cleanup_job,
    cron_schedule="0 3 * * *",  # daily at 03:00 UTC
)
def source_cleanup_schedule(context: dg.ScheduleEvaluationContext) -> dg.RunRequest:
    """Daily schedule for orphan Source node cleanup."""
    return dg.RunRequest()
