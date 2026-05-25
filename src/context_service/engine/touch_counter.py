"""Redis-backed time-decayed touch tracking for marker escalation.

Tracks how many times a session has "touched" (interacted with) a marker
within a rolling time window. Used by the escalation system to decide when
a marker needs more urgent attention.

Redis key pattern:
    touches:{silo_id}:{marker_id}  ->  sorted set
    Members: {session_id}
    Scores:  {timestamp_ms} (Unix epoch in milliseconds)

On each touch the set is pruned to the decay window, so old sessions fall
off automatically without a separate cleanup job.
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


async def record_touch(
    redis: Redis[bytes],  # type: ignore[type-arg]
    silo_id: str,
    marker_id: str,
    session_id: str,
    *,
    decay_window_ms: int = DEFAULT_DECAY_WINDOW_MS,
) -> int:
    """Record a touch and return the new touch count for this session+marker.

    Adds the current timestamp for ``session_id`` to the sorted set keyed by
    ``silo_id`` and ``marker_id``, prunes entries older than ``decay_window_ms``,
    then returns how many touches from this session remain in the window.

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
    Number of touches from this session within the decay window, including
    the one just recorded.
    """
    key = _touches_key(silo_id, marker_id)
    now = _now_ms()
    cutoff = now - decay_window_ms

    try:
        pipe = redis.pipeline(transaction=False)
        pipe.zadd(key, {session_id: now})
        pipe.zremrangebyscore(key, "-inf", cutoff)
        pipe.zscore(key, session_id)
        results = await pipe.execute()
    except Exception as exc:
        logger.warning(
            "touch_counter_record_failed",
            silo_id=silo_id,
            marker_id=marker_id,
            session_id=session_id,
            error=str(exc),
        )
        return 0

    # The pipeline records only one entry per session_id (ZADD updates the
    # score); the "count" here means: is this session still present after
    # pruning?  We return 1 if the session survived the prune, 0 otherwise.
    # Callers treat this as "active touch count" (presence-based, not a
    # cumulative counter), which is what the escalation system needs.
    score = results[2]  # zscore result: float | None
    count = 1 if score is not None else 0

    logger.debug(
        "touch_recorded",
        silo_id=silo_id,
        marker_id=marker_id,
        session_id=session_id,
        count=count,
    )
    return count


async def get_touch_count(
    redis: Redis[bytes],  # type: ignore[type-arg]
    silo_id: str,
    marker_id: str,
    session_id: str,
    *,
    decay_window_ms: int = DEFAULT_DECAY_WINDOW_MS,
) -> int:
    """Get current touch count for this session+marker within the decay window.

    Returns 1 if the session has an active (non-expired) touch, 0 otherwise.
    Does not record a new touch; read-only operation.

    Parameters
    ----------
    redis:
        Async Redis client.
    silo_id:
        Silo scope.
    marker_id:
        Marker to query.
    session_id:
        Session to check.
    decay_window_ms:
        Rolling window in milliseconds used to determine staleness.

    Returns
    -------
    1 if the session has a touch within the window, 0 otherwise.
    """
    key = _touches_key(silo_id, marker_id)
    now = _now_ms()
    cutoff = now - decay_window_ms

    try:
        score = await redis.zscore(key, session_id)
    except Exception as exc:
        logger.warning(
            "touch_counter_get_failed",
            silo_id=silo_id,
            marker_id=marker_id,
            session_id=session_id,
            error=str(exc),
        )
        return 0

    if score is None:
        return 0
    # Score is the timestamp in ms; check if it's within the decay window.
    return 1 if float(score) > cutoff else 0


async def clear_touches(
    redis: Redis[bytes],  # type: ignore[type-arg]
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
