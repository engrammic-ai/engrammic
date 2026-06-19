"""Signals subsystem: heat, freshness, priority, access-event emission.

Phase 1 (v1c): shipped stubbed heat (0.5) + real freshness, priority, and
live access-event emitters.
Phase 2 (v1c): real heat lookup backed by an hourly Dagster asset; cursor
management in signals.cursor.
"""

from __future__ import annotations

from context_service.signals.access_events import (
    ACCESS_STREAM_MAXLEN,
    access_stream_key,
    emit_access_event,
)
from context_service.signals.freshness import FRESHNESS_FLOOR, compute_freshness
from context_service.signals.heat import DEFAULT_HEAT
from context_service.signals.priority import compute_consensus_priority

__all__ = [
    "ACCESS_STREAM_MAXLEN",
    "DEFAULT_HEAT",
    "FRESHNESS_FLOOR",
    "access_stream_key",
    "compute_consensus_priority",
    "compute_freshness",
    "emit_access_event",
]
