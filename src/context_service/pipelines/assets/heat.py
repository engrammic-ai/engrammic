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
from context_service.signals.access_events import access_stream_key
from context_service.signals.heat import get_decay_multiplier


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


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

_FETCH_EXISTING_HEAT_CYPHER = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
RETURN n.id AS node_id,
       coalesce(n.heat_score, 0.0) AS heat_score,
       n.heat_updated_at AS heat_updated_at
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


def parse_event_type(fields: dict[str | bytes, str | bytes]) -> str:
    """Extract event_type from stream entry, defaulting to 'read'."""
    raw = fields.get(b"event_type") or fields.get("event_type")
    if raw is None:
        return "read"
    return raw.decode() if isinstance(raw, bytes) else raw


def parse_layer(fields: dict[str | bytes, str | bytes]) -> str | None:
    """Extract layer from stream entry. Returns None if not present."""
    raw = fields.get(b"layer") or fields.get("layer")
    if raw is None:
        return None
    return raw.decode() if isinstance(raw, bytes) else raw


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
        from uuid import UUID

        from sqlalchemy import select

        from context_service.db import get_session
        from context_service.models.postgres.org import SiloConfig as PGSiloConfig
        from context_service.signals.cursor import (
            advance_heat_cursor,
            fetch_or_init_heat_cursor,
        )
        from context_service.stores import MemgraphClient

        # Check if heat processing is enabled for this silo.
        silo_uuid = UUID(silo_id)
        async with get_session() as session:
            result = await session.execute(
                select(PGSiloConfig.feature_flags).where(PGSiloConfig.silo_id == silo_uuid)
            )
            row = result.scalar_one_or_none()
            feature_flags: dict[str, Any] = row if row is not None else {}
            heat_enabled: bool = bool(feature_flags.get("heat_enabled", True))

        if not heat_enabled:
            context.log.info(f"silo={silo_id} heat disabled via feature_flags, skipping")
            return 0, 0, "0-0"

        driver = await memgraph.driver()
        mg_client = MemgraphClient(driver)
        redis_conn = await redis.client()

        stream_key = access_stream_key(silo_id)
        last_id = await fetch_or_init_heat_cursor(mg_client, silo_id)  # type: ignore[arg-type]

        from context_service.config.settings import get_settings

        settings = get_settings()

        # Accumulate raw access counts and track layer per node.
        raw_counts: dict[str, float] = defaultdict(float)
        node_layers: dict[str, str | None] = {}
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
                    event_type = parse_event_type(fields)
                    weight = (
                        settings.heat_read_weight
                        if event_type == "read"
                        else settings.heat_write_weight
                    )
                    raw_counts[node_id] += weight
                    layer = parse_layer(fields)
                    if layer is not None:
                        node_layers[node_id] = layer
                eid = entry_id_b.decode() if isinstance(entry_id_b, bytes) else entry_id_b
                new_last_id = eid

        if not raw_counts:
            # Nothing new to process; still advance cursor if entries were read.
            if new_last_id != last_id:
                await advance_heat_cursor(mg_client, silo_id, new_last_id)  # type: ignore[arg-type]
            return 0, total_events, new_last_id

        # Fetch existing heat scores so we can apply time decay before combining
        # with the new contribution from this batch.
        existing_heat: dict[str, float] = {}
        existing_updated_at: dict[str, str | None] = {}
        existing_rows = await mg_client.execute_query(
            _FETCH_EXISTING_HEAT_CYPHER,
            {"silo_id": silo_id, "node_ids": list(raw_counts.keys())},
        )
        for row in existing_rows:
            nid = row["node_id"]
            existing_heat[nid] = float(row["heat_score"])
            existing_updated_at[nid] = row.get("heat_updated_at")

        now_dt = datetime.now(UTC)
        now_iso = now_dt.isoformat()

        # Convert raw counts to decay-weighted heat scores, blending with
        # time-decayed existing values.
        updates: list[dict[str, Any]] = []
        for node_id, count in raw_counts.items():
            # New contribution: normalise log(1 + count) / log(1 + XREAD_COUNT).
            new_contribution = min(1.0, math.log1p(count) / math.log1p(XREAD_COUNT))

            # Apply layer-based decay multiplier when unified decay is enabled.
            # Higher layers (Wisdom, Intelligence) retain heat longer.
            if settings.unified_decay_enabled:
                layer = node_layers.get(node_id)
                multiplier = get_decay_multiplier(layer)
                # Scale contribution by multiplier (normalised to 1.0-2.0 range).
                new_contribution = min(1.0, new_contribution * (1.0 + (multiplier - 1.0) * 0.25))

            # Decay the existing score based on time since last update.
            prior_heat = existing_heat.get(node_id, 0.0)
            prior_updated_at = existing_updated_at.get(node_id)
            if prior_heat > 0.0 and prior_updated_at is not None:
                try:
                    prior_dt = datetime.fromisoformat(prior_updated_at)
                    age_seconds = (now_dt - prior_dt).total_seconds()
                    decayed_prior = prior_heat * _decay_factor(max(0.0, age_seconds))
                except (ValueError, TypeError):
                    decayed_prior = 0.0
            else:
                decayed_prior = prior_heat

            heat = min(1.0, decayed_prior + new_contribution)

            updates.append({"node_id": node_id, "heat_score": heat, "tier": _tier(heat)})

        await mg_client.execute_write(
            _APPLY_HEAT_CYPHER,
            {"silo_id": silo_id, "updates": updates, "now": now_iso},
        )

        await advance_heat_cursor(mg_client, silo_id, new_last_id)  # type: ignore[arg-type]
        return len(updates), total_events, new_last_id

    nodes_updated, events_consumed, final_cursor = _run_async(_run())
    duration_s = time.monotonic() - t0
    skipped = nodes_updated == 0 and events_consumed == 0

    if skipped:
        context.log.info(f"silo={silo_id} skipped_no_work duration={duration_s:.2f}s")
    else:
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
            "skipped_no_work": skipped,
        },
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "nodes_updated": dg.MetadataValue.int(nodes_updated),
            "events_consumed": dg.MetadataValue.int(events_consumed),
            "final_cursor": dg.MetadataValue.text(final_cursor),
            "duration_s": dg.MetadataValue.float(duration_s),
            "skipped_no_work": dg.MetadataValue.bool(skipped),
        },
    )


__all__ = [
    "HEAT_HALF_LIFE_DAYS",
    "HOT_THRESHOLD",
    "WARM_THRESHOLD",
    "XREAD_COUNT",
    "heat_asset",
    "parse_event_type",
    "parse_layer",
]
