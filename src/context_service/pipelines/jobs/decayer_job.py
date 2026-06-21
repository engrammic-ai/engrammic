"""Dagster job for Memory confidence decay (SAGE Phase D).

decayer_op: query Memory nodes last accessed more than 1 hour ago and apply
exponential decay to their confidence scores. Deletion of nodes whose confidence
falls below threshold is handled by groundskeeper_nightly.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
import structlog
from dagster import ScheduleDefinition

from context_service.pipelines.resources import MemgraphResource

logger = structlog.get_logger(__name__)

_DEFAULT_DECAY_RATE = 0.95

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 100
"""

_LIST_MEMORY_NODES_DUE_DECAY = """
MATCH (m:Memory {silo_id: $silo_id})
WHERE m.properties.state = 'ACTIVE'
  AND m.properties.confidence IS NOT NULL
  AND (
    m.last_accessed_at IS NOT NULL AND m.last_accessed_at < $threshold_dt
    OR m.last_accessed_at IS NULL AND m.created_at < $threshold_dt
  )
RETURN m.id AS node_id,
       m.properties.confidence AS confidence,
       m.properties.decay_rate AS decay_rate,
       coalesce(m.last_accessed_at, m.created_at) AS last_accessed_at
LIMIT $batch_size
"""

_UPDATE_MEMORY_CONFIDENCE = """
MATCH (m:Memory {id: $node_id, silo_id: $silo_id})
SET m.properties.confidence = $new_confidence,
    m.updated_at = $now
"""


def decay_confidence(confidence: float, decay_rate: float, hours_since_access: float) -> float:
    return confidence * (decay_rate ** hours_since_access)


async def find_decay_candidates(
    store: Any,
    silo_id: str,
    threshold_dt: str,
    log: Any,
    batch_size: int = 500,
) -> list[dict[str, Any]]:
    rows = await store.execute_query(
        _LIST_MEMORY_NODES_DUE_DECAY,
        {"silo_id": silo_id, "threshold_dt": threshold_dt, "batch_size": batch_size},
    )
    log.info(f"decayer_op: silo={silo_id} decay_candidates={len(rows)}")
    return [dict(r) for r in rows]


async def apply_decay(
    store: Any,
    silo_id: str,
    candidates: list[dict[str, Any]],
    now_dt: str,
    log: Any,
) -> dict[str, int]:
    from datetime import UTC, datetime

    updated = 0
    skipped = 0
    errors = 0
    now = datetime.now(UTC)

    for row in candidates:
        node_id = row["node_id"]
        confidence = row.get("confidence")
        decay_rate = row.get("decay_rate") or _DEFAULT_DECAY_RATE
        raw_last_accessed = row.get("last_accessed_at")

        if confidence is None:
            skipped += 1
            continue

        try:
            if isinstance(raw_last_accessed, str):
                from dateutil.parser import parse as parse_dt

                last_accessed = parse_dt(raw_last_accessed)
                if last_accessed.tzinfo is None:
                    last_accessed = last_accessed.replace(tzinfo=UTC)
            elif isinstance(raw_last_accessed, datetime):
                last_accessed = raw_last_accessed
                if last_accessed.tzinfo is None:
                    last_accessed = last_accessed.replace(tzinfo=UTC)
            else:
                skipped += 1
                continue

            hours_since_access = (now - last_accessed).total_seconds() / 3600.0
            new_confidence = decay_confidence(float(confidence), float(decay_rate), hours_since_access)
            new_confidence = max(0.0, min(1.0, new_confidence))

            await store.execute_query(
                _UPDATE_MEMORY_CONFIDENCE,
                {"node_id": node_id, "silo_id": silo_id, "new_confidence": new_confidence, "now": now_dt},
            )
            updated += 1
            logger.debug(
                "decayer.updated",
                node_id=node_id,
                silo_id=silo_id,
                old_confidence=confidence,
                new_confidence=new_confidence,
                hours_since_access=hours_since_access,
            )
        except Exception as exc:
            errors += 1
            logger.error("decayer.error", node_id=node_id, silo_id=silo_id, error=str(exc))
            log.info(f"decayer_op: error node_id={node_id} silo={silo_id} error={exc}")

    return {"updated": updated, "skipped": skipped, "errors": errors}


@dg.op(required_resource_keys={"memgraph"})
def decayer_op(context) -> dict[str, int]:
    """Apply exponential confidence decay to stale Memory nodes."""
    from datetime import UTC, datetime, timedelta

    memgraph: MemgraphResource = context.resources.memgraph

    async def _run() -> dict[str, int]:
        store = await memgraph.store()
        now = datetime.now(UTC)
        threshold = now - timedelta(hours=1)
        threshold_dt = threshold.isoformat()
        now_dt = now.isoformat()

        silo_rows = await store.execute_query(_LIST_ACTIVE_SILOS, {})
        silos = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]
        context.log.info(f"decayer_op: scanning {len(silos)} silo(s)")

        total_updated = 0
        total_skipped = 0
        total_errors = 0

        for silo_id in silos:
            candidates = await find_decay_candidates(store, silo_id, threshold_dt, context.log)
            result = await apply_decay(store, silo_id, candidates, now_dt, context.log)
            total_updated += result["updated"]
            total_skipped += result["skipped"]
            total_errors += result["errors"]
            context.log.info(
                f"decayer_op: silo={silo_id} updated={result['updated']}"
                f" skipped={result['skipped']} errors={result['errors']}"
            )

        return {"updated": total_updated, "skipped": total_skipped, "errors": total_errors}

    result = asyncio.run(_run())
    context.log.info(
        f"decayer_op: done updated={result['updated']} skipped={result['skipped']} errors={result['errors']}"
    )
    return result


@dg.job(
    name="sage_decayer_job",
    description="SAGE Phase D: apply exponential confidence decay to stale Memory nodes hourly.",
)
def sage_decayer_job() -> None:
    """Memory confidence decay job."""
    decayer_op()


sage_decayer_schedule = ScheduleDefinition(
    job=sage_decayer_job,
    cron_schedule="0 * * * *",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
