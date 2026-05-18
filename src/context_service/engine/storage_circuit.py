"""Storage circuit breakers for Memgraph, Qdrant, and Redis.

Each storage backend has a dedicated CircuitBreaker instance keyed under
GLOBAL_SILO so that infrastructure health is process-wide, not per-tenant.

Behavior on open:
  Memgraph - raise StorageCircuitOpenError (source of truth, hard fail)
  Qdrant   - raise StorageCircuitOpenError (source of truth, hard fail)
  Redis    - return None / degrade silently  (optimization layer)

Default parameters match the D2 architectural decision:
  failure_threshold=5, window_s=60, cooldown_s=60
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable

import structlog

from context_service.engine.exceptions import StorageCircuitOpenError
from context_service.extraction.filter.circuit_breaker import CircuitBreaker, get_or_create
from context_service.telemetry.metrics import (
    record_circuit_breaker_closed,
    record_circuit_breaker_opened,
)

logger = structlog.get_logger(__name__)

# Silo key used for all infrastructure-level (non-tenant) circuit breakers.
GLOBAL_SILO = "__global__"

# Default D2 parameters.
_FAILURE_THRESHOLD = 5
_WINDOW_S = 60.0
_COOLDOWN_S = 60.0

# Store name constants (used as labels).
STORE_MEMGRAPH = "memgraph"
STORE_QDRANT = "qdrant"
STORE_REDIS = "redis"


async def _get_storage_cb(store: str) -> CircuitBreaker:
    """Return the singleton CircuitBreaker for the given store name."""
    return await get_or_create(
        GLOBAL_SILO,
        store,
        failure_threshold=_FAILURE_THRESHOLD,
        window_s=_WINDOW_S,
        cooldown_s=_COOLDOWN_S,
    )


async def _handle_open(cb: CircuitBreaker, store: str) -> None:
    """Raise StorageCircuitOpenError with the appropriate retry hint."""
    retry_after = await cb.retry_after_seconds()
    raise StorageCircuitOpenError(store=store, retry_after_seconds=retry_after)


async def _on_trip(store: str) -> None:
    """Called when a circuit transitions closed -> open."""
    logger.error(
        "storage_circuit_opened",
        store=store,
        transition="closed->open",
    )
    record_circuit_breaker_opened(store)


async def _on_reset(store: str) -> None:
    """Called when a circuit transitions open -> closed (cooldown elapsed)."""
    logger.info(
        "storage_circuit_closed",
        store=store,
        transition="open->closed",
    )
    record_circuit_breaker_closed(store)


async def guard_hard_fail[T](
    store: str,
    coro: Awaitable[T],
    *,
    is_infrastructure_error: type[Exception] | tuple[type[Exception], ...] | None = None,
) -> T:
    """Execute *coro*, recording infrastructure failures against *store*'s circuit breaker.

    If the circuit is open, raises StorageCircuitOpenError immediately.
    On trip (closed -> open) or reset (open -> closed), logs and emits metrics.

    Args:
        store: Store name label (e.g. STORE_MEMGRAPH).
        coro: Awaitable to execute.
        is_infrastructure_error: Exception type(s) that count as backend
            infrastructure failures and should trip the circuit.  When None,
            all exceptions trip the circuit.  Use this to exclude application
            errors (e.g. bad query syntax) from tripping.

    Raises:
        StorageCircuitOpenError: If the circuit is open before execution.
        Exception: Whatever *coro* raises (always re-raised).

    Suitable for Memgraph and Qdrant (hard-fail semantics).
    """
    cb = await _get_storage_cb(store)

    open_, just_closed = await cb.check_open()
    if just_closed:
        await _on_reset(store)
    if open_:
        if inspect.iscoroutine(coro):
            coro.close()
        await _handle_open(cb, store)

    try:
        result = await coro
    except Exception as exc:
        should_trip = is_infrastructure_error is None or isinstance(exc, is_infrastructure_error)
        if should_trip:
            tripped = await cb.record_failure()
            if tripped:
                await _on_trip(store)
        raise
    else:
        closed = await cb.record_success()
        if closed:
            await _on_reset(store)
        return result


async def guard_degrade[T](
    store: str,
    coro: Awaitable[T],
    default: T,
    *,
    is_infrastructure_error: type[Exception] | tuple[type[Exception], ...] | None = None,
) -> T:
    """Execute *coro* against *store*'s circuit breaker; degrade on open.

    If the circuit is open, returns *default* instead of raising.  On trip
    or reset, logs and emits metrics.

    Args:
        store: Store name label (e.g. STORE_REDIS).
        coro: Awaitable to execute.
        default: Value to return when circuit is open or on error.
        is_infrastructure_error: Exception type(s) that count as backend
            infrastructure failures and should trip the circuit.  When None,
            all exceptions trip the circuit.

    Suitable for Redis (optimization layer, degrade semantics).
    """
    cb = await _get_storage_cb(store)

    open_, just_closed = await cb.check_open()
    if just_closed:
        await _on_reset(store)
    if open_:
        if inspect.iscoroutine(coro):
            coro.close()
        logger.warning(
            "storage_circuit_open_degrading",
            store=store,
        )
        return default

    try:
        result2 = await coro
    except Exception as exc:
        should_trip = is_infrastructure_error is None or isinstance(exc, is_infrastructure_error)
        if should_trip:
            tripped = await cb.record_failure()
            if tripped:
                await _on_trip(store)
        # Do not re-raise; return default to degrade gracefully.
        logger.warning(
            "storage_circuit_degrade_on_error",
            store=store,
            exc_info=True,
        )
        return default
    else:
        closed = await cb.record_success()
        if closed:
            await _on_reset(store)
        return result2
