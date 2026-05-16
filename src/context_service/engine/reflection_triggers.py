"""Auto-reflection trigger helpers (v1.3d).

This module provides three trigger surfaces wired behind the
``auto_reflect.triggers_enabled`` feature flag:

1. **Rate limiter** — Redis counter per silo, capped at
   ``auto_reflect.max_reflections_per_hour`` (default 10).  Callers that exceed
   the cap receive ``False`` from :func:`check_rate_limit` and must skip the
   reflection.

2. **Confidence shift detection** — :func:`maybe_trigger_confidence_shift`
   compares the confidence value before and after a write.  When the absolute
   delta exceeds ``auto_reflect.confidence_shift_threshold`` the function
   enqueues a background task to call ``create_auto_reflection``.

3. **Contradiction detection** — :func:`maybe_trigger_contradiction` is called
   when a new claim is flagged as contradicting an existing Fact-layer node.
   It queues an auto-reflection of type ``"contradiction_detected"``.

4. **High-uncertainty annotation** — :func:`compute_reflection_suggested`
   returns ``True`` when the average confidence of query results falls below
   ``auto_reflect.uncertainty_threshold``.

All public helpers are no-ops when ``triggers_enabled`` is ``False`` or when
the Redis client is ``None``.  They never raise — failures are logged and
swallowed so they cannot affect the caller's write path.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings
from context_service.engine.auto_reflection import create_auto_reflection

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Redis key pattern for the hourly rolling counter.
# TTL is 3600 s so the key auto-expires after one hour.
_RATE_KEY_TEMPLATE = "auto_reflect:rate:{silo_id}"
_RATE_WINDOW_SECONDS = 3600


async def check_rate_limit(redis: Redis[bytes], silo_id: str) -> bool:  # type: ignore[type-arg]
    """Return ``True`` when the silo is within its hourly reflection budget.

    Increments the rolling counter and returns ``False`` (budget exhausted) if
    the new count exceeds ``max_reflections_per_hour``.  The counter key is set
    to expire in one hour on first creation.

    Safe to call even if ``triggers_enabled`` is ``False`` — callers are
    expected to guard that flag themselves.
    """
    cfg = get_settings().auto_reflect
    key = _RATE_KEY_TEMPLATE.format(silo_id=silo_id)
    try:
        count = int(await redis.incr(key))
        if count == 1:
            # First write in this window — set expiry.
            await redis.expire(key, _RATE_WINDOW_SECONDS)
        within_limit: bool = count <= cfg.max_reflections_per_hour
        if not within_limit:
            logger.debug(
                "auto_reflect_rate_limited",
                silo_id=silo_id,
                count=count,
                max=cfg.max_reflections_per_hour,
            )
        return within_limit
    except Exception as exc:
        # Redis failure → block the reflection (fail-closed).
        logger.warning(
            "auto_reflect_rate_limit_check_failed",
            silo_id=silo_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return False


def compute_reflection_suggested(results: list[dict[str, Any]]) -> bool:
    """Return ``True`` when average result confidence is below the uncertainty threshold.

    Parameters
    ----------
    results:
        List of result dicts, each optionally containing a ``"confidence"`` key.
        Entries without a confidence value contribute 1.0 (treated as high-confidence).
    """
    cfg = get_settings().auto_reflect
    if not cfg.triggers_enabled:
        return False
    if not results:
        return False
    total = sum(float(r.get("confidence") or 1.0) for r in results)
    avg = total / len(results)
    suggested = avg < cfg.uncertainty_threshold
    if suggested:
        logger.debug(
            "auto_reflect_uncertainty_flagged",
            avg_confidence=round(avg, 4),
            threshold=cfg.uncertainty_threshold,
        )
    return suggested


async def maybe_trigger_confidence_shift(
    store: HyperGraphStore,
    redis: Redis[bytes] | None,  # type: ignore[type-arg]
    silo_id: str,
    node_id: str,
    confidence_before: float,
    confidence_after: float,
) -> None:
    """Queue a background auto-reflection when confidence shifts beyond threshold.

    The caller provides the confidence value before and after the write.  If the
    absolute delta exceeds ``confidence_shift_threshold`` and the silo is within
    its rate limit, a ``"belief_change"`` MetaObservation is created.

    This function never raises.
    """
    cfg = get_settings().auto_reflect
    if not (cfg.enabled and cfg.triggers_enabled):
        return

    delta = abs(confidence_after - confidence_before)
    if delta <= cfg.confidence_shift_threshold:
        return

    if redis is not None and not await check_rate_limit(redis, silo_id):
        return

    content = (
        f"Confidence shifted by {delta:.2f} (from {confidence_before:.2f} "
        f"to {confidence_after:.2f}) on node {node_id}"
    )

    async def _write() -> None:
        try:
            await create_auto_reflection(
                store=store,
                observation_type="belief_change",
                content=content,
                about_node_ids=[node_id],
                silo_id=silo_id,
            )
        except Exception as exc:
            logger.warning(
                "auto_reflect_confidence_shift_failed",
                silo_id=silo_id,
                node_id=node_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    asyncio.get_running_loop().create_task(_write())


async def maybe_trigger_contradiction(
    store: HyperGraphStore,
    redis: Redis[bytes] | None,  # type: ignore[type-arg]
    silo_id: str,
    new_node_id: str,
    contradicted_node_id: str,
) -> None:
    """Queue a background auto-reflection for a detected contradiction.

    Called when a new claim contradicts an existing Fact-layer node.  Creates a
    ``"contradiction_detected"`` MetaObservation linked to both nodes.

    This function never raises.
    """
    cfg = get_settings().auto_reflect
    if not (cfg.enabled and cfg.triggers_enabled):
        return

    if redis is not None and not await check_rate_limit(redis, silo_id):
        return

    content = f"New claim {new_node_id} contradicts existing fact {contradicted_node_id}"

    async def _write() -> None:
        try:
            await create_auto_reflection(
                store=store,
                observation_type="contradiction_detected",
                content=content,
                about_node_ids=[new_node_id, contradicted_node_id],
                silo_id=silo_id,
            )
        except Exception as exc:
            logger.warning(
                "auto_reflect_contradiction_failed",
                silo_id=silo_id,
                new_node_id=new_node_id,
                contradicted_node_id=contradicted_node_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    asyncio.get_running_loop().create_task(_write())
