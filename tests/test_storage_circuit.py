"""Unit tests for storage circuit breakers (D2)."""

from __future__ import annotations

import pytest

from context_service.engine.exceptions import StorageCircuitOpenError
from context_service.engine.storage_circuit import (
    _COOLDOWN_S,
    _FAILURE_THRESHOLD,
    _WINDOW_S,
    GLOBAL_SILO,
    STORE_MEMGRAPH,
    STORE_QDRANT,
    STORE_REDIS,
    guard_degrade,
    guard_hard_fail,
)
from context_service.extraction.filter import circuit_breaker

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cb_registry() -> None:
    """Reset the CB registry between tests to avoid state leak."""
    circuit_breaker._registry.clear()


# ---------------------------------------------------------------------------
# Helper coroutines
# ---------------------------------------------------------------------------


async def _ok(value: str = "ok") -> str:
    return value


async def _fail(exc: Exception | None = None) -> str:
    raise exc or RuntimeError("boom")


# ---------------------------------------------------------------------------
# guard_hard_fail - success path
# ---------------------------------------------------------------------------


async def test_guard_hard_fail_passes_through_return_value() -> None:
    result = await guard_hard_fail(STORE_MEMGRAPH, _ok("data"))
    assert result == "data"


async def test_guard_hard_fail_re_raises_exception() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        await guard_hard_fail(STORE_MEMGRAPH, _fail())


# ---------------------------------------------------------------------------
# guard_hard_fail - circuit trip
# ---------------------------------------------------------------------------


async def test_guard_hard_fail_trips_after_threshold() -> None:
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_MEMGRAPH, _fail())

    # Next call should see the circuit open
    with pytest.raises(StorageCircuitOpenError) as exc_info:
        await guard_hard_fail(STORE_MEMGRAPH, _ok())

    err = exc_info.value
    assert err.store == STORE_MEMGRAPH
    assert err.retry_after_seconds > 0.0


async def test_guard_hard_fail_uses_global_silo() -> None:
    """CB is keyed under GLOBAL_SILO, not a tenant silo."""
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_MEMGRAPH, _fail())

    # The key in the registry should be (GLOBAL_SILO, STORE_MEMGRAPH)
    key = (GLOBAL_SILO, STORE_MEMGRAPH)
    assert key in circuit_breaker._registry


async def test_guard_hard_fail_records_success_and_resets() -> None:
    """After threshold-1 failures, a success clears the slate."""
    for _ in range(_FAILURE_THRESHOLD - 1):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_MEMGRAPH, _fail())

    # Success before threshold: circuit stays closed
    result = await guard_hard_fail(STORE_MEMGRAPH, _ok("good"))
    assert result == "good"

    # After success, subsequent failures need a fresh run to the threshold
    for _ in range(_FAILURE_THRESHOLD - 1):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_MEMGRAPH, _fail())

    # Still not open yet
    result2 = await guard_hard_fail(STORE_MEMGRAPH, _ok("still-good"))
    assert result2 == "still-good"


# ---------------------------------------------------------------------------
# guard_hard_fail - per-store isolation
# ---------------------------------------------------------------------------


async def test_memgraph_and_qdrant_have_separate_circuits() -> None:
    """Trips to STORE_MEMGRAPH do not affect STORE_QDRANT."""
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_MEMGRAPH, _fail())

    # Memgraph circuit is open
    with pytest.raises(StorageCircuitOpenError) as exc_info:
        await guard_hard_fail(STORE_MEMGRAPH, _ok())
    assert exc_info.value.store == STORE_MEMGRAPH

    # Qdrant circuit is independent
    result = await guard_hard_fail(STORE_QDRANT, _ok("qdrant-ok"))
    assert result == "qdrant-ok"


# ---------------------------------------------------------------------------
# guard_degrade - success path
# ---------------------------------------------------------------------------


async def test_guard_degrade_passes_through_return_value() -> None:
    result = await guard_degrade(STORE_REDIS, _ok("cached"), default="miss")
    assert result == "cached"


async def test_guard_degrade_returns_default_on_error() -> None:
    result = await guard_degrade(STORE_REDIS, _fail(), default="miss")
    assert result == "miss"


async def test_guard_degrade_does_not_raise_on_error() -> None:
    # Should NOT raise — just return default
    result = await guard_degrade(STORE_REDIS, _fail(RuntimeError("redis down")), default=None)
    assert result is None


# ---------------------------------------------------------------------------
# guard_degrade - circuit open behaviour
# ---------------------------------------------------------------------------


async def test_guard_degrade_returns_default_when_circuit_open() -> None:
    # Trip the Redis circuit
    for _ in range(_FAILURE_THRESHOLD):
        await guard_degrade(STORE_REDIS, _fail(), default=None)

    # Now circuit should be open; degrade without calling the (already-tripped) coro
    result = await guard_degrade(STORE_REDIS, _ok("would-not-run"), default="degraded")
    assert result == "degraded"


async def test_guard_degrade_does_not_raise_when_circuit_open() -> None:
    for _ in range(_FAILURE_THRESHOLD):
        await guard_degrade(STORE_REDIS, _fail(), default=None)

    # No exception
    result = await guard_degrade(STORE_REDIS, _fail(), default="safe")
    assert result == "safe"


# ---------------------------------------------------------------------------
# retry_after_seconds on StorageCircuitOpenError
# ---------------------------------------------------------------------------


async def test_retry_after_seconds_is_positive_when_circuit_open() -> None:
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(RuntimeError):
            await guard_hard_fail(STORE_QDRANT, _fail())

    with pytest.raises(StorageCircuitOpenError) as exc_info:
        await guard_hard_fail(STORE_QDRANT, _ok())

    assert exc_info.value.retry_after_seconds > 0.0
    assert exc_info.value.retry_after_seconds <= _COOLDOWN_S


# ---------------------------------------------------------------------------
# check_open transition detection
# ---------------------------------------------------------------------------


async def test_check_open_detects_cooldown_reset() -> None:
    """check_open returns just_closed=True when cooldown elapses."""
    fake_time = [0.0]

    cb = circuit_breaker.CircuitBreaker(
        failure_threshold=1,
        window_s=60.0,
        cooldown_s=10.0,
        now_fn=lambda: fake_time[0],
    )

    # Open it
    await cb.record_failure()
    assert await cb.is_open()

    # Advance past cooldown
    fake_time[0] = 11.0
    open_, just_closed = await cb.check_open()
    assert not open_
    assert just_closed


async def test_check_open_just_closed_false_when_still_open() -> None:
    fake_time = [0.0]

    cb = circuit_breaker.CircuitBreaker(
        failure_threshold=1,
        window_s=60.0,
        cooldown_s=10.0,
        now_fn=lambda: fake_time[0],
    )

    await cb.record_failure()
    fake_time[0] = 5.0  # not past cooldown yet
    open_, just_closed = await cb.check_open()
    assert open_
    assert not just_closed


# ---------------------------------------------------------------------------
# Default parameters match D2 spec
# ---------------------------------------------------------------------------


def test_d2_default_parameters() -> None:
    assert _FAILURE_THRESHOLD == 5
    assert _WINDOW_S == 60.0
    assert _COOLDOWN_S == 60.0


def test_global_silo_constant() -> None:
    assert GLOBAL_SILO == "__global__"


# ---------------------------------------------------------------------------
# is_infrastructure_error filter
# ---------------------------------------------------------------------------


class _AppError(Exception):
    pass


class _InfraError(Exception):
    pass


async def test_guard_hard_fail_only_trips_on_infrastructure_errors() -> None:
    """Application errors (e.g. bad query) do not trip the circuit."""
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(_AppError):
            await guard_hard_fail(
                STORE_MEMGRAPH,
                _fail(_AppError("bad syntax")),
                is_infrastructure_error=_InfraError,
            )

    # Circuit should still be closed (app errors excluded)
    result = await guard_hard_fail(
        STORE_MEMGRAPH,
        _ok("still-up"),
        is_infrastructure_error=_InfraError,
    )
    assert result == "still-up"


async def test_guard_hard_fail_trips_on_infrastructure_errors() -> None:
    """Infrastructure errors do trip the circuit."""
    for _ in range(_FAILURE_THRESHOLD):
        with pytest.raises(_InfraError):
            await guard_hard_fail(
                STORE_QDRANT,
                _fail(_InfraError("connection refused")),
                is_infrastructure_error=_InfraError,
            )

    with pytest.raises(StorageCircuitOpenError):
        await guard_hard_fail(STORE_QDRANT, _ok(), is_infrastructure_error=_InfraError)
