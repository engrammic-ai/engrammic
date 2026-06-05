"""Reaction event schema and emission helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Timeout (seconds) for enqueue operations - fire-and-forget
_EMIT_TIMEOUT_SECONDS: float = 0.5


class ReactionEventType(StrEnum):
    """Typed event identifiers for async reaction processing.

    Most event types have corresponding task handlers in tasks.py. Three are
    notification-only signals with no handler - they are emitted for logging
    and observability but do not trigger task execution:

    - CASCADE_STALENESS_COMPLETE: Signals cascade finished (no action needed)
    - CONFLICT_DETECTED: Signals conflict found (handled inline, not async)
    - CHECK_EXTRACTION_TRIGGER: Reserved for future extraction pipeline
    """

    COMPUTE_EMBEDDING = "compute_embedding"
    BATCH_COMPUTE_EMBEDDING = "batch_compute_embedding"  # batched version
    CASCADE_STALENESS = "cascade_staleness"
    CASCADE_STALENESS_COMPLETE = "cascade_staleness_complete"  # notification-only
    UPDATE_HEAT = "update_heat"
    UPDATE_CLUSTER_MEMBERSHIP = "update_cluster_membership"
    FLAG_CONTRADICTION = "flag_contradiction"
    CONFLICT_DETECTED = "conflict_detected"  # notification-only
    CHECK_SYNTHESIS = "check_synthesis"
    CHECK_EXTRACTION_TRIGGER = "check_extraction_trigger"  # notification-only
    PROPAGATE_CONFIDENCE = "propagate_confidence"
    CONSOLIDATE = "consolidate"


@dataclass
class ReactionEvent:
    """Event emitted for async reaction processing."""

    event_type: ReactionEventType | str
    node_id: str
    silo_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


async def emit_reaction(event: ReactionEvent) -> None:
    """Enqueue a reaction event to the Taskiq broker.

    Fire-and-forget: waits at most ``_EMIT_TIMEOUT_SECONDS`` for the enqueue
    to complete. If the queue is unavailable or the timeout expires, the error
    is logged but not re-raised so the calling transaction is not affected.

    Silo isolation is enforced at the task level via the ``silo_id`` kwarg,
    not at the queue level - all silos share the same queue.

    ``COMPUTE_EMBEDDING`` events are intercepted before broker dispatch and
    routed to the batch accumulator so that embeddings are processed in
    token-budget batches rather than one task per node.

    Args:
        event: The reaction event to enqueue.
    """
    # For embedding events, delegate to the batch accumulator instead of
    # dispatching an individual task.  The accumulator flushes automatically
    # when the batch is full or the flush interval elapses.
    if event.event_type == ReactionEventType.COMPUTE_EMBEDDING:
        try:
            from context_service.reactions.batch_embedding import (
                get_batch_embedding_accumulator,
            )

            accumulator = get_batch_embedding_accumulator()
            await accumulator.add(node_id=event.node_id, silo_id=event.silo_id)
            logger.debug(
                "reaction_emit_batched",
                event_type=event.event_type,
                node_id=event.node_id,
                silo_id=event.silo_id,
            )
        except Exception:
            logger.exception(
                "reaction_emit_batch_accumulator_failed",
                event_type=event.event_type,
                node_id=event.node_id,
                silo_id=event.silo_id,
            )
        return

    from context_service.reactions.broker import get_broker

    broker = get_broker()

    try:
        # Tasks are registered on the broker with @broker.task.
        # We kick the task by name so this module does not need to import
        # the task functions (avoids a circular-import chain).
        kicker = broker.find_task(event.event_type)
        if kicker is None:
            logger.warning(
                "reaction_task_not_registered",
                event_type=event.event_type,
                node_id=event.node_id,
                silo_id=event.silo_id,
            )
            return

        await asyncio.wait_for(
            kicker.kiq(
                node_id=event.node_id,
                silo_id=event.silo_id,
                **event.payload,
            ),
            timeout=_EMIT_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning(
            "reaction_emit_timeout",
            event_type=event.event_type,
            node_id=event.node_id,
            silo_id=event.silo_id,
            timeout=_EMIT_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.exception(
            "reaction_emit_failed",
            event_type=event.event_type,
            node_id=event.node_id,
            silo_id=event.silo_id,
        )
