"""Dagster sensor: trigger extraction partition when new :Document nodes arrive."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg

from context_service.pipelines.resources import MemgraphResource
from context_service.utils.json import JSONDecodeError, dumps, loads

_PENDING_DOC_COUNT = """
MATCH (d:Document {silo_id: $silo_id})
WHERE NOT EXISTS((d)<-[:EXTRACTED_FROM]-(:Claim))
RETURN count(d) AS pending
"""

_LIST_ACTIVE_SILOS = """
MATCH (d:Document)
RETURN DISTINCT d.silo_id AS silo_id
"""

_PENDING_THRESHOLD = 1
_STALENESS_MINUTES = 5


def _parse_cursor(cursor: str | None) -> dict[str, str]:
    if not cursor:
        return {}
    try:
        data: dict[str, str] = loads(cursor)
        return data
    except JSONDecodeError:
        return {}


def _parse_iso_datetime(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@dg.sensor(
    name="document_arrival_sensor",
    asset_selection=dg.AssetSelection.assets("extraction", "embedding"),
    minimum_interval_seconds=60,
    description="Triggers extraction and embedding assets for silos with pending :Document nodes.",
)
def document_arrival_sensor(
    context: dg.SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Poll for pending documents per silo and request extraction runs."""

    async def _poll() -> list[dict[str, Any]]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)

        silo_rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        silo_ids = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]

        triggers: list[dict[str, Any]] = []
        now = datetime.now(UTC)
        cursor_data = _parse_cursor(context.cursor)

        for silo_id in silo_ids:
            count_rows = await client.execute_query(_PENDING_DOC_COUNT, {"silo_id": silo_id})
            pending = int(count_rows[0]["pending"]) if count_rows else 0

            last_run = _parse_iso_datetime(cursor_data.get(silo_id, ""))
            stale = pending > 0 and (
                last_run is None or (now - last_run) > timedelta(minutes=_STALENESS_MINUTES)
            )

            if pending >= _PENDING_THRESHOLD or stale:
                triggers.append({"silo_id": silo_id, "pending": pending, "now": now.isoformat()})

        return triggers

    triggers = asyncio.run(_poll())
    if not triggers:
        return dg.SensorResult(run_requests=[], cursor=context.cursor or "{}")

    cursor_data = _parse_cursor(context.cursor)
    run_requests: list[dg.RunRequest] = []
    for t in triggers:
        silo_id: str = t["silo_id"]
        run_requests.append(
            dg.RunRequest(
                run_key=f"ingest:{silo_id}:{t['now']}",
                partition_key=silo_id,
                tags={"dagster/concurrency_key": silo_id},
            )
        )
        cursor_data[silo_id] = t["now"]
        context.log.info(
            f"triggering extraction+embedding for silo={silo_id} pending={t['pending']}"
        )

    return dg.SensorResult(run_requests=run_requests, cursor=dumps(cursor_data))
