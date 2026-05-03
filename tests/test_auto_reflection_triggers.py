"""Tests for engine/reflection_triggers.py (v1.3d)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.engine.reflection_triggers import (
    check_rate_limit,
    compute_reflection_suggested,
    maybe_trigger_confidence_shift,
    maybe_trigger_contradiction,
)
from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(
    enabled: bool = True,
    triggers_enabled: bool = True,
    confidence_shift_threshold: float = 0.2,
    uncertainty_threshold: float = 0.4,
    max_reflections_per_hour: int = 10,
) -> MagicMock:
    cfg = MagicMock()
    cfg.auto_reflect.enabled = enabled
    cfg.auto_reflect.triggers_enabled = triggers_enabled
    cfg.auto_reflect.confidence_shift_threshold = confidence_shift_threshold
    cfg.auto_reflect.uncertainty_threshold = uncertainty_threshold
    cfg.auto_reflect.max_reflections_per_hour = max_reflections_per_hour
    return cfg


def _fake_redis(count: int = 1) -> MagicMock:
    redis = MagicMock()
    redis.incr = AsyncMock(return_value=count)
    redis.expire = AsyncMock(return_value=True)
    return redis


async def _drain() -> None:
    """Yield control so that background tasks created by create_task can run."""
    for _ in range(5):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_rate_limit_within_budget() -> None:
    redis = _fake_redis(count=1)
    settings = _make_settings(max_reflections_per_hour=10)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        result = await check_rate_limit(redis, "silo-1")
    assert result is True
    redis.incr.assert_awaited_once()
    redis.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_rate_limit_at_exactly_max() -> None:
    redis = _fake_redis(count=10)
    settings = _make_settings(max_reflections_per_hour=10)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        result = await check_rate_limit(redis, "silo-1")
    assert result is True


@pytest.mark.asyncio
async def test_check_rate_limit_exceeds_budget() -> None:
    redis = _fake_redis(count=11)
    settings = _make_settings(max_reflections_per_hour=10)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        result = await check_rate_limit(redis, "silo-1")
    assert result is False


@pytest.mark.asyncio
async def test_check_rate_limit_no_expire_on_subsequent_increments() -> None:
    """expire should only be called when count == 1 (first write in window)."""
    redis = _fake_redis(count=5)
    settings = _make_settings(max_reflections_per_hour=10)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await check_rate_limit(redis, "silo-1")
    redis.expire.assert_not_awaited()


@pytest.mark.asyncio
async def test_check_rate_limit_redis_failure_fails_open() -> None:
    redis = MagicMock()
    redis.incr = AsyncMock(side_effect=RuntimeError("redis down"))
    settings = _make_settings()
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        result = await check_rate_limit(redis, "silo-1")
    # Fail-open: returns True so the reflection is not suppressed.
    assert result is True


# ---------------------------------------------------------------------------
# compute_reflection_suggested
# ---------------------------------------------------------------------------


def test_compute_reflection_suggested_low_confidence() -> None:
    results = [{"confidence": 0.1}, {"confidence": 0.2}]
    settings = _make_settings(triggers_enabled=True, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested(results) is True


def test_compute_reflection_suggested_high_confidence() -> None:
    results = [{"confidence": 0.9}, {"confidence": 0.95}]
    settings = _make_settings(triggers_enabled=True, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested(results) is False


def test_compute_reflection_suggested_exactly_at_threshold() -> None:
    # avg == threshold → not suggested (strictly less than)
    results = [{"confidence": 0.4}]
    settings = _make_settings(triggers_enabled=True, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested(results) is False


def test_compute_reflection_suggested_empty_results() -> None:
    settings = _make_settings(triggers_enabled=True, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested([]) is False


def test_compute_reflection_suggested_flag_off() -> None:
    results = [{"confidence": 0.01}]
    settings = _make_settings(triggers_enabled=False, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested(results) is False


def test_compute_reflection_suggested_missing_confidence_treated_as_high() -> None:
    # One low (0.1), one missing (defaults to 1.0) → avg = 0.55 → above threshold
    results = [{"confidence": 0.1}, {}]
    settings = _make_settings(triggers_enabled=True, uncertainty_threshold=0.4)
    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        assert compute_reflection_suggested(results) is False


# ---------------------------------------------------------------------------
# maybe_trigger_confidence_shift
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_trigger_confidence_shift_fires_above_threshold() -> None:
    store = FakeGraphStore()
    store.seed_write_result([])
    redis = _fake_redis(count=1)
    settings = _make_settings(enabled=True, triggers_enabled=True, confidence_shift_threshold=0.2)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_confidence_shift(
            store=store,
            redis=redis,
            silo_id="silo-1",
            node_id="node-abc",
            confidence_before=0.5,
            confidence_after=0.8,  # delta = 0.3 > 0.2
        )

    await _drain()

    assert len(store.write_log) == 1
    _, params = store.write_log[0]
    assert params["observation_type"] == "belief_change"
    assert "node-abc" in params["about_node_ids"]


@pytest.mark.asyncio
async def test_maybe_trigger_confidence_shift_skips_below_threshold() -> None:
    store = FakeGraphStore()
    redis = _fake_redis(count=1)
    settings = _make_settings(confidence_shift_threshold=0.2)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_confidence_shift(
            store=store,
            redis=redis,
            silo_id="silo-1",
            node_id="node-xyz",
            confidence_before=0.5,
            confidence_after=0.6,  # delta = 0.1 <= 0.2
        )

    await _drain()
    assert len(store.write_log) == 0


@pytest.mark.asyncio
async def test_maybe_trigger_confidence_shift_flag_off() -> None:
    store = FakeGraphStore()
    redis = _fake_redis(count=1)
    settings = _make_settings(enabled=True, triggers_enabled=False)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_confidence_shift(
            store=store,
            redis=redis,
            silo_id="silo-1",
            node_id="node-xyz",
            confidence_before=0.0,
            confidence_after=1.0,
        )

    await _drain()
    assert len(store.write_log) == 0


@pytest.mark.asyncio
async def test_maybe_trigger_confidence_shift_rate_limited() -> None:
    store = FakeGraphStore()
    redis = _fake_redis(count=99)  # over limit
    settings = _make_settings(max_reflections_per_hour=10)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_confidence_shift(
            store=store,
            redis=redis,
            silo_id="silo-1",
            node_id="node-xyz",
            confidence_before=0.0,
            confidence_after=1.0,
        )

    await _drain()
    assert len(store.write_log) == 0


@pytest.mark.asyncio
async def test_maybe_trigger_confidence_shift_no_redis() -> None:
    """When redis is None the rate limit is skipped and the trigger still fires."""
    store = FakeGraphStore()
    store.seed_write_result([])
    settings = _make_settings(enabled=True, triggers_enabled=True, confidence_shift_threshold=0.2)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_confidence_shift(
            store=store,
            redis=None,
            silo_id="silo-1",
            node_id="node-n",
            confidence_before=0.0,
            confidence_after=0.9,
        )

    await _drain()
    assert len(store.write_log) == 1


# ---------------------------------------------------------------------------
# maybe_trigger_contradiction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_trigger_contradiction_fires() -> None:
    store = FakeGraphStore()
    store.seed_write_result([])
    redis = _fake_redis(count=1)
    settings = _make_settings(enabled=True, triggers_enabled=True)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_contradiction(
            store=store,
            redis=redis,
            silo_id="silo-1",
            new_node_id="node-new",
            contradicted_node_id="node-old",
        )

    await _drain()

    assert len(store.write_log) == 1
    _, params = store.write_log[0]
    assert params["observation_type"] == "contradiction_detected"
    assert "node-new" in params["about_node_ids"]
    assert "node-old" in params["about_node_ids"]


@pytest.mark.asyncio
async def test_maybe_trigger_contradiction_flag_off() -> None:
    store = FakeGraphStore()
    redis = _fake_redis(count=1)
    settings = _make_settings(enabled=True, triggers_enabled=False)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_contradiction(
            store=store,
            redis=redis,
            silo_id="silo-1",
            new_node_id="node-new",
            contradicted_node_id="node-old",
        )

    await _drain()
    assert len(store.write_log) == 0


@pytest.mark.asyncio
async def test_maybe_trigger_contradiction_rate_limited() -> None:
    store = FakeGraphStore()
    redis = _fake_redis(count=99)
    settings = _make_settings(max_reflections_per_hour=10)

    with patch(
        "context_service.engine.reflection_triggers.get_settings",
        return_value=settings,
    ):
        await maybe_trigger_contradiction(
            store=store,
            redis=redis,
            silo_id="silo-1",
            new_node_id="node-new",
            contradicted_node_id="node-old",
        )

    await _drain()
    assert len(store.write_log) == 0
