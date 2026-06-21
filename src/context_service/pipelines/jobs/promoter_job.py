"""Dagster job for promoting eligible Claims to Facts (SAGE Phase B).

find_promotion_candidates: query ACTIVE/UNPROMOTED Claims and verify corroboration.
promote_candidates: call promote() for each candidate, handle races gracefully.
"""

from __future__ import annotations

import asyncio
from typing import Any

import dagster as dg
import structlog
from dagster import ScheduleDefinition

from context_service.pipelines.resources import MemgraphResource
from context_service.sage.transactions import (
    PROMOTION_THRESHOLD,
    InvariantViolation,
    promote,
)

logger = structlog.get_logger(__name__)

_LIST_ACTIVE_SILOS = """
MATCH (n) WHERE n.silo_id IS NOT NULL RETURN DISTINCT n.silo_id AS silo_id LIMIT 100
"""

_LIST_UNPROMOTED_CLAIMS = """
MATCH (c:Claim {silo_id: $silo_id})
WHERE c.properties.state = 'ACTIVE'
  AND c.properties.claim_status = 'UNPROMOTED'
  AND c.properties.corroboration_count >= $threshold
RETURN c.id AS claim_id,
       c.properties.confidence AS confidence,
       c.properties.corroboration_count AS corroboration_count
LIMIT $batch_size
"""


async def find_promotion_candidates(store: Any, log: Any) -> list[dict[str, Any]]:
    """Return Claims that meet the promotion threshold across all active silos.

    Each item: {"claim_id": str, "silo_id": str, "corroboration_count": int}
    """
    silo_rows = await store.execute_query(_LIST_ACTIVE_SILOS, {})
    silos = [str(r["silo_id"]) for r in silo_rows if r.get("silo_id")]
    log.info(f"promoter_op: scanning {len(silos)} silo(s)")

    candidates: list[dict[str, Any]] = []

    for silo_id in silos:
        rows = await store.execute_query(
            _LIST_UNPROMOTED_CLAIMS,
            {"silo_id": silo_id, "threshold": PROMOTION_THRESHOLD, "batch_size": 100},
        )
        log.info(f"promoter_op: silo={silo_id} unpromoted_claims={len(rows)}")

        for row in rows:
            claim_id: str = row["claim_id"]
            corroboration_count: int = row["corroboration_count"]
            candidates.append(
                {
                    "claim_id": claim_id,
                    "silo_id": silo_id,
                    "corroboration_count": corroboration_count,
                }
            )
            log.info(
                f"promoter_op: candidate claim_id={claim_id} silo={silo_id}"
                f" corroboration={corroboration_count}"
            )

    return candidates


async def promote_candidates(store: Any, candidates: list[dict[str, Any]], log: Any) -> dict[str, int]:
    """Call promote() for each candidate; skip on InvariantViolation (race condition)."""
    promoted = 0
    skipped = 0
    errors = 0

    for candidate in candidates:
        claim_id: str = candidate["claim_id"]
        silo_id: str = candidate["silo_id"]
        corroboration_count: int | None = candidate.get("corroboration_count")

        try:
            await promote(
                store,
                claim_id,
                silo_id,
                corroboration_count=corroboration_count,
                emit=True,
            )
            promoted += 1
            logger.info(
                "promoter.promoted",
                claim_id=claim_id,
                silo_id=silo_id,
                corroboration_count=corroboration_count,
            )
            log.info(f"promoter_op: promoted claim_id={claim_id} silo={silo_id}")
        except InvariantViolation as exc:
            # Race with write-time promotion path or precondition no longer holds.
            skipped += 1
            code = exc.code if hasattr(exc, "code") else str(exc)
            logger.info(
                "promoter.skipped",
                claim_id=claim_id,
                silo_id=silo_id,
                reason=code,
            )
            log.info(
                f"promoter_op: skipped claim_id={claim_id} silo={silo_id} reason={code}"
            )
        except Exception as exc:
            errors += 1
            logger.error(
                "promoter.error",
                claim_id=claim_id,
                silo_id=silo_id,
                error=str(exc),
            )
            log.info(
                f"promoter_op: error claim_id={claim_id} silo={silo_id} error={exc}"
            )

    return {"promoted": promoted, "skipped": skipped, "errors": errors}


@dg.op(required_resource_keys={"memgraph"})
def promoter_op(context) -> dict[str, int]:
    """Promote eligible Claims to Facts."""
    memgraph: MemgraphResource = context.resources.memgraph

    async def _run() -> dict[str, int]:
        store = await memgraph.store()
        candidates = await find_promotion_candidates(store, context.log)
        context.log.info(f"promoter_op: found {len(candidates)} candidate(s)")
        return await promote_candidates(store, candidates, context.log)

    result = asyncio.run(_run())
    context.log.info(
        f"promoter_op: done promoted={result['promoted']} skipped={result['skipped']} errors={result['errors']}"
    )
    return result


@dg.job(
    name="sage_promoter_job",
    description="SAGE Phase B: promote eligible Claims to Facts every 5 minutes.",
)
def sage_promoter_job() -> None:
    """Claim-to-fact promotion job."""
    promoter_op()


sage_promoter_schedule = ScheduleDefinition(
    job=sage_promoter_job,
    cron_schedule="*/5 * * * *",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
