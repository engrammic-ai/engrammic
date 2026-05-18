# src/context_service/pipelines/jobs/orphan_recovery.py
"""Orphan chain recovery Dagster job.

Recovers reasoning chains that failed to write to Memgraph. Uses exponential
backoff with max 5 retries before alerting.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog
from dagster import Out, Output, job, op, schedule
from sqlalchemy import delete, select, update

from context_service.db.postgres import get_session
from context_service.models.postgres.reasoning import OrphanedChains, ReasoningChainSteps
from context_service.telemetry.metrics import (
    ORPHAN_CHAINS_EXHAUSTED,
    ORPHAN_CHAINS_RECOVERED,
)

log = structlog.get_logger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_MINUTES = 5


def backoff_elapsed(retry_count: int, last_retry_at: datetime | None) -> bool:
    """Check if enough time has passed for next retry."""
    if last_retry_at is None:
        return True
    wait_minutes = (2**retry_count) * BASE_BACKOFF_MINUTES
    return datetime.now(UTC) > last_retry_at + timedelta(minutes=wait_minutes)


async def fetch_chain_from_postgres(chain_id: UUID) -> dict[str, object]:
    """Fetch full chain data from Postgres for Memgraph projection.

    Returns a dict with chain_id, silo_id, steps (list of step dicts), and step_count.
    Raises ValueError if the chain has no steps stored.
    """
    async with get_session() as session:
        result = await session.execute(
            select(ReasoningChainSteps).where(ReasoningChainSteps.chain_id == chain_id)
        )
        row: ReasoningChainSteps | None = result.scalars().one_or_none()
        if row is None or not row.steps:
            raise ValueError(f"No steps found for chain {chain_id}")

        steps: list[dict[str, object]] = [
            {"content": s.get("content", ""), "step_index": s.get("step_index", i)}
            for i, s in enumerate(row.steps)
        ]
        return {
            "chain_id": str(chain_id),
            "silo_id": str(row.silo_id),
            "steps": steps,
            "step_count": len(steps),
        }


async def delete_orphan(orphan_id: UUID) -> None:
    """Delete recovered orphan from dead-letter table."""
    async with get_session() as session:
        await session.execute(delete(OrphanedChains).where(OrphanedChains.chain_id == orphan_id))
        await session.commit()


async def increment_retry(orphan_id: UUID) -> None:
    """Increment retry count and update last_retry_at."""
    async with get_session() as session:
        await session.execute(
            update(OrphanedChains)
            .where(OrphanedChains.chain_id == orphan_id)
            .values(
                retry_count=OrphanedChains.retry_count + 1,
                last_retry_at=datetime.now(UTC),
            )
        )
        await session.commit()


@op(out={"eligible": Out(), "exhausted": Out()})
def fetch_orphaned_chains(context) -> Any:
    """Fetch chains eligible for retry and those exhausted."""

    async def _fetch() -> tuple[list[OrphanedChains], list[OrphanedChains]]:
        async with get_session() as session:
            # Eligible for retry
            result = await session.execute(
                select(OrphanedChains).where(OrphanedChains.retry_count < MAX_RETRIES)
            )
            chains: list[OrphanedChains] = list(result.scalars().all())
            eligible = [c for c in chains if backoff_elapsed(c.retry_count, c.last_retry_at)]

            # Exhausted (for alerting)
            exhausted_result = await session.execute(
                select(OrphanedChains).where(OrphanedChains.retry_count >= MAX_RETRIES)
            )
            exhausted: list[OrphanedChains] = list(exhausted_result.scalars().all())

            return eligible, exhausted

    eligible, exhausted = asyncio.run(_fetch())
    context.log.info(f"Found {len(eligible)} eligible orphans, {len(exhausted)} exhausted")
    yield Output(eligible, output_name="eligible")
    yield Output(exhausted, output_name="exhausted")


@op
def retry_chains_to_memgraph(context, eligible: list[OrphanedChains]) -> dict[str, int]:
    """Attempt to write chain projections to Memgraph."""
    results: dict[str, int] = {"success": 0, "failed": 0}

    async def _retry() -> dict[str, int]:
        from context_service.mcp.server import get_context_service

        ctx = get_context_service()
        store = ctx._memgraph

        for orphan in eligible:
            try:
                chain_data = await fetch_chain_from_postgres(orphan.chain_id)
                raw_steps = chain_data.get("steps", [])
                steps: list[dict[str, object]] = raw_steps if isinstance(raw_steps, list) else []
                raw_count = chain_data.get("step_count", 0)
                step_count = raw_count if isinstance(raw_count, int) else len(steps)
                first_step = json.dumps(steps[0]) if steps else None
                final_step = json.dumps(steps[-1]) if steps else None
                all_premise_refs: list[str] = []
                for s in steps:
                    refs = s.get("premise_refs")
                    if isinstance(refs, list):
                        all_premise_refs.extend(str(r) for r in refs)

                await store.upsert_reasoning_chain(
                    chain_id=str(chain_data["chain_id"]),
                    silo_id=str(chain_data["silo_id"]),
                    step_count=step_count,
                    first_step=first_step,
                    final_step=final_step,
                    outcome=None,
                    all_premise_refs=all_premise_refs,
                    produced_by_model="unknown",
                    produced_by_agent_id="unknown",
                    status="recovered",
                    source="orphan_recovery",
                )
                await delete_orphan(orphan.chain_id)
                results["success"] += 1
                ORPHAN_CHAINS_RECOVERED(str(orphan.silo_id))
                log.info("orphan_chain_recovered", chain_id=str(orphan.chain_id))
            except Exception as e:
                await increment_retry(orphan.chain_id)
                results["failed"] += 1
                log.warning(
                    "orphan_chain_retry_failed",
                    chain_id=str(orphan.chain_id),
                    retry_count=orphan.retry_count + 1,
                    error=str(e),
                )
        return results

    return asyncio.run(_retry())


@op
def alert_exhausted_chains(context, exhausted: list[OrphanedChains]) -> None:
    """Alert on chains that hit max retries."""
    if not exhausted:
        return

    log.error(
        "orphan_chains_exhausted",
        count=len(exhausted),
        chain_ids=[str(c.chain_id) for c in exhausted],
    )

    for orphan in exhausted:
        ORPHAN_CHAINS_EXHAUSTED(str(orphan.silo_id))


@job
def orphan_chain_recovery_job():
    """Recover orphaned reasoning chains."""
    eligible, exhausted = fetch_orphaned_chains()
    retry_chains_to_memgraph(eligible)
    alert_exhausted_chains(exhausted)


@schedule(
    job=orphan_chain_recovery_job,
    cron_schedule="0 * * * *",  # hourly
)
def orphan_recovery_schedule(context):
    """Hourly schedule for orphan recovery."""
    return {}
