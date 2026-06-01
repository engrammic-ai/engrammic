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
    """Typed event identifiers for async reaction processing."""

    COMPUTE_EMBEDDING = "compute_embedding"
    CASCADE_STALENESS = "cascade_staleness"
    CASCADE_STALENESS_COMPLETE = "cascade_staleness_complete"
    UPDATE_HEAT = "update_heat"
    UPDATE_CLUSTER_MEMBERSHIP = "update_cluster_membership"
    FLAG_CONTRADICTION = "flag_contradiction"
    CONFLICT_DETECTED = "conflict_detected"
    CHECK_SYNTHESIS = "check_synthesis"
    CHECK_EXTRACTION_TRIGGER = "check_extraction_trigger"
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

    Args:
        event: The reaction event to enqueue.
    """
    from context_service.reactions.broker import get_broker

    broker = get_broker(event.silo_id)

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
