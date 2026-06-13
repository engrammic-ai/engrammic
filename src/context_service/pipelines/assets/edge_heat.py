"""Dagster asset: hourly edge heat scoring per silo.

Mirrors the node heat asset pattern. Drains the per-silo Redis edge access
events stream, applies exponential decay to accumulate a heat score for each
traversed edge (WeakLink node), writes w.edge_heat to Memgraph, then advances
the :EdgeHeatCursor singleton so the next run starts where this one left off.
"""

import asyncio
import concurrent.futures
import math
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import (
    AssetExecutionContext,  # noqa: F401 (re-exported for Dagster annotation resolution)
)

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource
from context_service.signals.edge_access_events import edge_access_stream_key

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------

EDGE_HEAT_HALF_LIFE_DAYS = 7
XREAD_COUNT = 10_000

# ------------------------------------------------------------------
# Cypher
# ------------------------------------------------------------------

APPLY_EDGE_HEAT_CYPHER = """
UNWIND $updates AS u
MATCH (w:WeakLink {id: u.link_id, silo_id: $silo_id})
SET w.edge_heat = u.heat_score,
    w.heat_updated_at = $now
"""

_GET_EDGE_HEAT_CURSOR_CYPHER = """
MATCH (c:EdgeHeatCursor {silo_id: $silo_id})
RETURN c.last_id AS last_id
"""

_SET_EDGE_HEAT_CURSOR_CYPHER = """
MERGE (c:EdgeHeatCursor {silo_id: $silo_id})
SET c.last_id = $last_id, c.updated_at = $now
"""

_FETCH_EXISTING_EDGE_HEAT_CYPHER = """
UNWIND $link_ids AS lid
MATCH (w:WeakLink {id: lid, silo_id: $silo_id})
RETURN w.id AS link_id,
       coalesce(w.edge_heat, 0.0) AS edge_heat,
       w.heat_updated_at AS heat_updated_at
"""


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


def _decay_factor(age_seconds: float) -> float:
    """Exponential decay with EDGE_HEAT_HALF_LIFE_DAYS half-life."""
    half_life_s = EDGE_HEAT_HALF_LIFE_DAYS * 86400.0
    return math.pow(0.5, age_seconds / half_life_s)


@dg.asset(
    name="edge_heat",
    partitions_def=silo_partitions,
    deps=["heat"],
    description=(
        "Drain per-silo edge access-events stream, compute decay-weighted heat "
        "scores, write edge_heat to WeakLink nodes in Memgraph, advance :EdgeHeatCursor."
    ),
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "edge_heat"},
)
def edge_heat_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Compute and persist edge heat scores for all traversed WeakLink edges in the silo."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, str]:
        from context_service.engine.protocols import HyperGraphStore
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        redis_conn = await redis.client()

        # Fetch cursor
        cursor_result = await mg_client.execute_query(
            _GET_EDGE_HEAT_CURSOR_CYPHER, {"silo_id": silo_id}
        )
        last_id = "0-0"
        if cursor_result:
            raw = cursor_result[0].get("last_id")
            if raw is not None:
                last_id = raw

        stream_key = edge_access_stream_key(silo_id)
        entries = await redis_conn.xread(
            {stream_key: last_id},
            count=XREAD_COUNT,
        )

        heat_acc: dict[str, float] = defaultdict(float)
        new_last_id = last_id
        total_events = 0

        if entries:
            _key_b, messages = entries[0]
            for entry_id_b, fields in messages:
                total_events += 1
                raw_eid = fields.get(b"edge_id") or fields.get("edge_id")
                if raw_eid is not None:
                    eid = raw_eid.decode() if isinstance(raw_eid, bytes) else raw_eid
                    heat_acc[eid] += 1.0
                new_last_id = entry_id_b.decode() if isinstance(entry_id_b, bytes) else entry_id_b

        if not heat_acc:
            if new_last_id != last_id:
                now_iso = datetime.now(UTC).isoformat()
                await mg_client.execute_write(
                    _SET_EDGE_HEAT_CURSOR_CYPHER,
                    {"silo_id": silo_id, "last_id": new_last_id, "now": now_iso},
                )
            return 0, total_events, new_last_id

        # Fetch existing edge heat scores so we can apply time decay before
        # combining with the new contribution from this batch.
        existing_heat: dict[str, float] = {}
        existing_updated_at: dict[str, str | None] = {}
        existing_rows = await mg_client.execute_query(
            _FETCH_EXISTING_EDGE_HEAT_CYPHER,
            {"silo_id": silo_id, "link_ids": list(heat_acc.keys())},
        )
        for row in existing_rows:
            lid = row["link_id"]
            existing_heat[lid] = float(row["edge_heat"])
            existing_updated_at[lid] = row.get("heat_updated_at")

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        # Convert raw counts to decay-weighted heat scores, blending with
        # time-decayed existing values.
        updates: list[dict[str, Any]] = []
        for eid, count in heat_acc.items():
            # New contribution: normalise log(1 + count) / log(1 + XREAD_COUNT).
            new_contribution = min(1.0, math.log1p(count) / math.log1p(XREAD_COUNT))

            # Decay the existing score based on time since last update.
            prior_heat = existing_heat.get(eid, 0.0)
            prior_updated_at = existing_updated_at.get(eid)
            if prior_heat > 0.0 and prior_updated_at is not None:
                try:
                    prior_dt = datetime.fromisoformat(prior_updated_at)
                    age_seconds = (now_dt - prior_dt).total_seconds()
                    decayed_prior = prior_heat * _decay_factor(max(0.0, age_seconds))
                except (ValueError, TypeError):
                    decayed_prior = 0.0
            else:
                decayed_prior = prior_heat

            heat_score = min(1.0, decayed_prior + new_contribution)
            updates.append({"link_id": eid, "heat_score": heat_score})

        await mg_client.execute_write(
            APPLY_EDGE_HEAT_CYPHER,
            {"silo_id": silo_id, "updates": updates, "now": now_iso},
        )

        await mg_client.execute_write(
            _SET_EDGE_HEAT_CURSOR_CYPHER,
            {"silo_id": silo_id, "last_id": new_last_id, "now": now_iso},
        )

        return len(updates), total_events, new_last_id

    edges_updated, events_consumed, final_cursor = _run_async(_run())
    duration_s = time.monotonic() - t0
    skipped = edges_updated == 0 and events_consumed == 0

    if skipped:
        context.log.info(f"silo={silo_id} skipped_no_work duration={duration_s:.2f}s")
    else:
        context.log.info(
            f"silo={silo_id} edges_updated={edges_updated} "
            f"events_consumed={events_consumed} cursor={final_cursor} "
            f"duration={duration_s:.2f}s"
        )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "edges_updated": edges_updated,
            "events_consumed": events_consumed,
            "final_cursor": final_cursor,
            "duration_s": duration_s,
            "skipped_no_work": skipped,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "edges_updated": dg.MetadataValue.int(edges_updated),
            "events_consumed": dg.MetadataValue.int(events_consumed),
            "final_cursor": dg.MetadataValue.text(final_cursor),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped),
        },
    )


__all__ = [
    "APPLY_EDGE_HEAT_CYPHER",
    "EDGE_HEAT_HALF_LIFE_DAYS",
    "XREAD_COUNT",
    "edge_heat_asset",
]
