"""Redis-backed time-decayed touch tracking for marker escalation.

Tracks how many times a session has "touched" (interacted with) a marker
within a rolling time window. Used by the escalation system to decide when
a marker needs more urgent attention.

Redis key pattern:
    touches:{silo_id}:{marker_id}  ->  sorted set
    Members: {session_id}:{timestamp_ns}  (unique per touch)
    Scores:  {timestamp_ms} (Unix epoch in milliseconds)

Each touch creates a distinct member so cumulative counts are preserved
within the decay window. On each touch the set is pruned to the decay
window, so old entries fall off automatically without a separate cleanup job.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = structlog.get_logger(__name__)

DEFAULT_DECAY_WINDOW_MS = 1_800_000  # 30 minutes

_TOUCHES_KEY = "touches:{silo_id}:{marker_id}"


def _touches_key(silo_id: str, marker_id: str) -> str:
    return _TOUCHES_KEY.format(silo_id=silo_id, marker_id=marker_id)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _now_ns() -> int:
    return time.time_ns()


async def record_touch(
    redis: Redis,
    silo_id: str,
    marker_id: str,
    session_id: str,
    *,
    decay_window_ms: int = DEFAULT_DECAY_WINDOW_MS,
) -> int:
    """Record a touch and return the new cumulative touch count for this session+marker.

    Adds a unique member ``{session_id}:{timestamp_ns}`` to the sorted set keyed
    by ``silo_id`` and ``marker_id``, prunes entries older than
    ``decay_window_ms``, then returns the total number of touches from this
    session that remain in the window.

    Failures are logged and swallowed; returns 0 on error.

    Parameters
    ----------
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    marker_id:
        Marker being touched.
    session_id:
        Session performing the touch.
    decay_window_ms:
        Rolling window in milliseconds. Touches older than this are pruned.

    Returns
    -------
    Cumulative number of touches from this session within the decay window,
    including the one just recorded.
    """
    key = _touches_key(silo_id, marker_id)
    now = _now_ms()
    cutoff = now - decay_window_ms
    member = f"{session_id}:{_now_ns()}"
    prefix = f"{session_id}:"

    try:
        pipe = redis.pipeline(transaction=False)
        pipe.zadd(key, {member: now})
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zrangebyscore(key, cutoff + 1, "+inf")
        results = await pipe.execute()
        members: list[bytes] | list[str] = results[2]
        count = sum(
            1 for m in members if (m.decode() if isinstance(m, bytes) else m).startswith(prefix)
        )
    except Exception as exc:
        logger.warning(
            "touch_counter_record_failed",
            silo_id=silo_id,
            marker_id=marker_id,
            session_id=session_id,
            error=str(exc),
        )
        return 0

    logger.debug(
        "touch_recorded",
        silo_id=silo_id,
        marker_id=marker_id,
        session_id=session_id,
        count=count,
    )
    return count


async def clear_touches(
    redis: Redis,
    silo_id: str,
    marker_id: str,
) -> None:
    """Clear all touches for a marker (called on resolution).

    Deletes the entire sorted set for the marker.  Failures are logged and
    swallowed; the graph record is the authoritative state.

    Parameters
    ----------
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    marker_id:
        Marker whose touch data should be erased.
    """
    key = _touches_key(silo_id, marker_id)
    try:
        await redis.delete(key)
    except Exception as exc:
        logger.warning(
            "touch_counter_clear_failed",
            silo_id=silo_id,
            marker_id=marker_id,
            error=str(exc),
        )
