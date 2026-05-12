"""Dagster assets for reasoning chain feedback tracking.

After a chain is delivered to an agent, this asset observes subsequent steps
within the same session to compute an implicit usefulness signal.

Signal classification:
  useful     — DTW overlap between chain steps and subsequent agent steps > 0.7
  not_useful — no high overlap AND a new chain was created for a similar query
  unclear    — insufficient data or no strong signal
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext  # noqa: F401


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


async def get_recent_deliveries(hours: int = 1, delay_minutes: int = 5) -> list[dict[str, Any]]:
    """Return chain deliveries from the last N hours, excluding recent ones.

    Args:
        hours: Look back this many hours for deliveries.
        delay_minutes: Exclude deliveries newer than this (wait for subsequent steps).
    """
    from sqlalchemy import select

    from context_service.db import get_session
    from context_service.models.postgres.chain_feedback import ChainDelivery

    cutoff_old = datetime.now(UTC) - timedelta(hours=hours)
    cutoff_recent = datetime.now(UTC) - timedelta(minutes=delay_minutes)

    async with get_session() as session:
        result = await session.execute(
            select(ChainDelivery).where(
                ChainDelivery.delivered_at > cutoff_old,
                ChainDelivery.delivered_at < cutoff_recent,  # Exclude too-recent
            )
        )
        rows = result.scalars().all()
        return [
            {
                "session_id": str(r.session_id),
                "chain_id": str(r.chain_id),
                "query": r.query,
                "delivered_at": r.delivered_at,
            }
            for r in rows
        ]


async def store_feedback(chain_id: str, signal: str) -> None:
    """Persist a usefulness signal for a chain and emit a metric."""
    from uuid import UUID

    from context_service.db import get_session
    from context_service.models.postgres.chain_feedback import ChainFeedback
    from context_service.telemetry.metrics import record_chain_feedback

    async with get_session() as session:
        feedback = ChainFeedback(chain_id=UUID(chain_id), signal=signal)
        session.add(feedback)
        await session.commit()

    record_chain_feedback(signal)


async def get_session_steps_after(
    session_id: str,  # noqa: ARG001
    after: datetime,  # noqa: ARG001
    limit: int,  # noqa: ARG001
) -> list[list[float]]:
    """Return step embeddings created in a session after the given timestamp.

    Stub — concrete implementation depends on the session/graph store.
    """
    return []


async def get_chain_step_embeddings(chain_id: str) -> list[list[float]]:  # noqa: ARG001
    """Return the step embeddings stored for a chain.

    Stub — concrete implementation depends on the graph/Qdrant store.
    """
    return []


async def check_new_chain_created(
    session_id: str,  # noqa: ARG001
    after: datetime,  # noqa: ARG001
    query: str,  # noqa: ARG001
) -> bool:
    """Return True if a new chain was created for a similar query after *after*.

    Stub — concrete implementation depends on the graph store.
    """
    return False


async def compute_chain_usefulness(delivery: dict[str, Any]) -> str | None:
    """Compute and persist a usefulness signal for a single delivery.

    Returns the signal string if one was stored, or None when skipped.
    """
    from context_service.config.settings import get_settings
    from context_service.engine.dtw import dtw_similarity

    config = get_settings().chain_feedback

    # Collect subsequent agent steps in this session after chain delivery.
    subsequent_steps = await get_session_steps_after(
        session_id=delivery["session_id"],
        after=delivery["delivered_at"],
        limit=config.min_subsequent_steps + 5,
    )

    if len(subsequent_steps) < config.min_subsequent_steps:
        return None  # Not enough data yet.

    chain_steps = await get_chain_step_embeddings(delivery["chain_id"])
    if not chain_steps:
        return None

    overlap = dtw_similarity(chain_steps, subsequent_steps)

    if overlap > 0.7:
        signal = "useful"
    elif await check_new_chain_created(
        session_id=delivery["session_id"],
        after=delivery["delivered_at"],
        query=delivery["query"],
    ):
        signal = "not_useful"
    else:
        signal = "unclear"

    await store_feedback(delivery["chain_id"], signal=signal)
    return signal


@dg.asset(
    name="chain_usefulness_signals",
    description="Computes usefulness signals for delivered reasoning chains",
    group_name="chain_feedback",
)
def chain_usefulness_signals(context) -> dg.Output[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Analyze recent chain deliveries and compute implicit usefulness signals."""
    t0 = time.monotonic()

    async def _run() -> tuple[int, int, int, int]:
        from context_service.config.settings import get_settings

        config = get_settings().chain_feedback
        deliveries = await get_recent_deliveries(
            hours=1,
            delay_minutes=config.evaluation_delay_minutes,
        )
        processed = useful = not_useful = unclear = 0

        for delivery in deliveries:
            try:
                signal = await compute_chain_usefulness(delivery)
                if signal is not None:
                    processed += 1
                    if signal == "useful":
                        useful += 1
                    elif signal == "not_useful":
                        not_useful += 1
                    else:
                        unclear += 1
            except Exception as exc:
                context.log.warning(f"Failed to process delivery {delivery['chain_id']}: {exc}")

        return len(deliveries), processed, useful, not_useful

    deliveries_count, processed, useful, not_useful = _run_async(_run())
    duration_s = time.monotonic() - t0

    context.log.info(
        f"chain_feedback deliveries={deliveries_count} processed={processed} "
        f"useful={useful} not_useful={not_useful} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={
            "deliveries": deliveries_count,
            "processed": processed,
            "useful": useful,
            "not_useful": not_useful,
            "duration_s": duration_s,
        },
        metadata={
            "deliveries": dg.MetadataValue.int(deliveries_count),
            "processed": dg.MetadataValue.int(processed),
            "useful": dg.MetadataValue.int(useful),
            "not_useful": dg.MetadataValue.int(not_useful),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = [
    "chain_usefulness_signals",
    "compute_chain_usefulness",
    "get_chain_step_embeddings",
    "get_recent_deliveries",
    "get_session_steps_after",
    "check_new_chain_created",
    "store_feedback",
]
