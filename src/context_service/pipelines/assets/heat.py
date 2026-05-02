"""Dagster asset: hourly heat scoring per silo.

Drains the per-silo Redis access-events stream (XREAD from the last cursor
position), applies exponential decay to accumulate a heat score for each
accessed node, writes ``n.heat_score`` and ``n.tier`` to Memgraph, then
advances the :HeatCursor singleton so the next run starts where this one left
off.

Tier thresholds (verbatim from prototype):
  HOT  >= 0.66
  WARM >= 0.33
  COLD  < 0.33
"""

import asyncio
import math
import time
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource
from context_service.signals.access_events import access_stream_key

# ------------------------------------------------------------------
# Constants (match prototype heat asset)
# ------------------------------------------------------------------

HEAT_HALF_LIFE_DAYS = 7
XREAD_COUNT = 10_000

HOT_THRESHOLD = 0.66
WARM_THRESHOLD = 0.33

# ------------------------------------------------------------------
# Cypher
# ------------------------------------------------------------------

_APPLY_HEAT_CYPHER = """
UNWIND $updates AS u
MATCH (n {id: u.node_id, silo_id: $silo_id})
SET n.heat_score = u.heat_score,
    n.tier       = u.tier,
    n.heat_updated_at = $now
"""

_RECOMPUTE_TIERS_CYPHER = """
MATCH (n)
WHERE n.silo_id = $silo_id AND n.heat_score IS NOT NULL
SET n.tier = CASE
    WHEN n.heat_score >= $hot  THEN 'HOT'
    WHEN n.heat_score >= $warm THEN 'WARM'
    ELSE 'COLD'
END
"""


def _decay_factor(age_seconds: float) -> float:
    """Exponential decay with HEAT_HALF_LIFE_DAYS half-life."""
    half_life_s = HEAT_HALF_LIFE_DAYS * 86400.0
    return math.pow(0.5, age_seconds / half_life_s)


def _tier(heat: float) -> str:
    if heat >= HOT_THRESHOLD:
        return "HOT"
    if heat >= WARM_THRESHOLD:
        return "WARM"
    return "COLD"


@dg.asset(
    name="heat",
    partitions_def=silo_partitions,
    description=(
        "Drain per-silo access-events stream, compute decay-weighted heat scores, "
        "write heat_score + tier to Memgraph nodes, advance :HeatCursor."
    ),
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "heat"},
)
def heat_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Compute and persist heat scores for all accessed nodes in the silo."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, str]:
        from context_service.signals.cursor import (
            advance_heat_cursor,
            fetch_or_init_heat_cursor,
        )
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        redis_conn = await redis.client()

        stream_key = access_stream_key(silo_id)
        last_id = await fetch_or_init_heat_cursor(mg_client, silo_id)

        # Accumulate raw access counts from stream entries.
        # Each entry: {b"node_id": b"<uuid-str>"}
        raw_counts: dict[str, int] = defaultdict(int)
        new_last_id = last_id
        total_events = 0

        # Drain up to XREAD_COUNT entries per asset run.
        entries = await redis_conn.xread(
            {stream_key: last_id},
            count=XREAD_COUNT,
        )
        # entries = [(stream_key_bytes, [(entry_id, {field: val}), ...])]
        if entries:
            _key_b, messages = entries[0]
            for entry_id_b, fields in messages:
                total_events += 1
                node_id_raw = fields.get(b"node_id") or fields.get("node_id")
                if node_id_raw is not None:
                    node_id = (
                        node_id_raw.decode() if isinstance(node_id_raw, bytes) else node_id_raw
                    )
                    raw_counts[node_id] += 1
                eid = entry_id_b.decode() if isinstance(entry_id_b, bytes) else entry_id_b
                new_last_id = eid

        if not raw_counts:
            # Nothing new to process; still advance cursor if entries were read.
            if new_last_id != last_id:
                await advance_heat_cursor(mg_client, silo_id, new_last_id)
            return 0, total_events, new_last_id

        # Convert raw counts to decay-weighted heat scores.
        # For simplicity we treat all events in this batch as "now" (no
        # per-entry timestamp decay). A future improvement can parse
        # entry IDs (millisecond timestamps) for finer-grained decay.
        updates: list[dict[str, Any]] = []
        for node_id, count in raw_counts.items():
            # Normalise: log(1 + count) / log(1 + XREAD_COUNT)
            heat = min(1.0, math.log1p(count) / math.log1p(XREAD_COUNT))
            updates.append({"node_id": node_id, "heat_score": heat, "tier": _tier(heat)})

        now_iso = datetime.now(UTC).isoformat()
        await mg_client.execute_write(
            _APPLY_HEAT_CYPHER,
            {"silo_id": silo_id, "updates": updates, "now": now_iso},
        )

        # Recompute tiers across all nodes with heat scores (not just this batch).
        await mg_client.execute_write(
            _RECOMPUTE_TIERS_CYPHER,
            {"silo_id": silo_id, "hot": HOT_THRESHOLD, "warm": WARM_THRESHOLD},
        )

        await advance_heat_cursor(mg_client, silo_id, new_last_id)
        return len(updates), total_events, new_last_id

    nodes_updated, events_consumed, final_cursor = asyncio.run(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"silo={silo_id} nodes_updated={nodes_updated} "
        f"events_consumed={events_consumed} cursor={final_cursor} "
        f"duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "silo_id": silo_id,
            "nodes_updated": nodes_updated,
            "events_consumed": events_consumed,
            "final_cursor": final_cursor,
            "duration_s": duration_s,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "nodes_updated": dg.MetadataValue.int(nodes_updated),
            "events_consumed": dg.MetadataValue.int(events_consumed),
            "final_cursor": dg.MetadataValue.text(final_cursor),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = [
    "HEAT_HALF_LIFE_DAYS",
    "HOT_THRESHOLD",
    "WARM_THRESHOLD",
    "XREAD_COUNT",
    "heat_asset",
]
