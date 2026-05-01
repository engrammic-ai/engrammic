"""Signals subsystem: heat, freshness, priority, access-event emission.

Phase 1 (v1c): stubs heat at 0.5; ships real freshness, priority, and live
access-event emitters.
Phase 2 (after partner talks): replaces the heat stub with a Memgraph read
backed by an hourly Dagster asset.
"""

from __future__ import annotations

from context_service.signals.access_events import (
    ACCESS_STREAM_MAXLEN,
    access_stream_key,
    emit_access_event,
)
from context_service.signals.freshness import FRESHNESS_FLOOR, compute_freshness
from context_service.signals.heat import STUB_HEAT_VALUE, get_heat
from context_service.signals.priority import compute_consensus_priority

__all__ = [
    "ACCESS_STREAM_MAXLEN",
    "FRESHNESS_FLOOR",
    "STUB_HEAT_VALUE",
    "access_stream_key",
    "compute_consensus_priority",
    "compute_freshness",
    "emit_access_event",
    "get_heat",
]
