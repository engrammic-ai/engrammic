"""Tests for engine/touch_counter.py — Redis-backed time-decayed touch tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.engine.touch_counter import (
    clear_touches,
    get_touch_count,
    record_touch,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Mock redis.asyncio.Redis with pipeline and zscore support."""
    redis = AsyncMock()

    pipe = AsyncMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zscore = MagicMock(return_value=pipe)
    pipe.__aenter__ = AsyncMock(return_value=pipe)
    pipe.__aexit__ = AsyncMock(return_value=None)

    redis.pipeline = MagicMock(return_value=pipe)
    redis._mock_pipe = pipe
    return redis


# ---------------------------------------------------------------------------
# record_touch
# ---------------------------------------------------------------------------


class TestRecordTouch:
    @pytest.mark.asyncio
    async def test_single_touch_returns_one(self, mock_redis):
        """First touch for a session returns count=1."""
        now_ms = 1_000_000
        # pipeline execute returns: [zadd_result, zremrangebyscore_result, zscore_result]
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[1, 0, float(now_ms)])

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 1

    @pytest.mark.asyncio
    async def test_touch_increments_for_same_session(self, mock_redis):
        """Repeated touches from the same session keep returning 1 (presence-based)."""
        now_ms = 2_000_000
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, 0, float(now_ms)])

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 1

    @pytest.mark.asyncio
    async def test_different_sessions_tracked_independently(self, mock_redis):
        """Different session IDs are stored as separate members."""
        now_ms = 3_000_000

        call_count = 0

        async def execute_side_effect() -> list[object]:
            nonlocal call_count
            call_count += 1
            return [1, 0, float(now_ms)]

        mock_redis._mock_pipe.execute = AsyncMock(side_effect=execute_side_effect)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            r1 = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")
            r2 = await record_touch(mock_redis, "silo-1", "marker-1", "session-b")

        assert r1 == 1
        assert r2 == 1
        # Each call used a separate pipeline invocation
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_decayed_touch_returns_zero(self, mock_redis):
        """If zscore returns None after pruning, count is 0."""
        now_ms = 4_000_000
        # zscore returns None -> session was pruned
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, 1, None])

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(
                mock_redis,
                "silo-1",
                "marker-1",
                "session-old",
                decay_window_ms=100,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_redis_error_returns_zero(self, mock_redis):
        """Redis failure is swallowed and returns 0."""
        mock_redis._mock_pipe.execute = AsyncMock(side_effect=ConnectionError("down"))

        result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 0

    @pytest.mark.asyncio
    async def test_uses_correct_key(self, mock_redis):
        """Verifies the Redis key format is touches:{silo_id}:{marker_id}."""
        now_ms = 5_000_000
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[1, 0, float(now_ms)])

        pipe = mock_redis._mock_pipe
        zadd_calls: list[tuple[object, ...]] = []
        original_zadd = pipe.zadd

        def capture_zadd(*args: object, **kwargs: object) -> object:
            zadd_calls.append(args)
            return original_zadd(*args, **kwargs)

        pipe.zadd = MagicMock(side_effect=capture_zadd)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            await record_touch(mock_redis, "silo-xyz", "marker-abc", "sess-1")

        assert zadd_calls, "zadd was never called"
        key_used = zadd_calls[0][0]
        assert key_used == "touches:silo-xyz:marker-abc"


# ---------------------------------------------------------------------------
# get_touch_count
# ---------------------------------------------------------------------------


class TestGetTouchCount:
    @pytest.mark.asyncio
    async def test_active_touch_returns_one(self, mock_redis):
        """Session with recent score returns 1."""
        now_ms = 10_000_000
        # Score is well within the window (now_ms itself)
        mock_redis.zscore = AsyncMock(return_value=float(now_ms))

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 1

    @pytest.mark.asyncio
    async def test_no_touch_returns_zero(self, mock_redis):
        """Session not in set returns 0."""
        mock_redis.zscore = AsyncMock(return_value=None)

        result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-new")

        assert result == 0

    @pytest.mark.asyncio
    async def test_expired_touch_returns_zero(self, mock_redis):
        """Score older than decay window returns 0."""
        now_ms = 20_000_000
        decay_window_ms = 1_000
        old_score = float(now_ms - decay_window_ms - 1)  # just outside the window
        mock_redis.zscore = AsyncMock(return_value=old_score)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(
                mock_redis,
                "silo-1",
                "marker-1",
                "session-old",
                decay_window_ms=decay_window_ms,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_touch_exactly_at_boundary_returns_zero(self, mock_redis):
        """Score exactly at cutoff is not within window (strictly greater than)."""
        now_ms = 20_000_000
        decay_window_ms = 1_000
        cutoff = float(now_ms - decay_window_ms)
        mock_redis.zscore = AsyncMock(return_value=cutoff)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(
                mock_redis,
                "silo-1",
                "marker-1",
                "session-boundary",
                decay_window_ms=decay_window_ms,
            )

        assert result == 0

    @pytest.mark.asyncio
    async def test_redis_error_returns_zero(self, mock_redis):
        """Redis failure is swallowed and returns 0."""
        mock_redis.zscore = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 0


# ---------------------------------------------------------------------------
# clear_touches
# ---------------------------------------------------------------------------


class TestClearTouches:
    @pytest.mark.asyncio
    async def test_deletes_correct_key(self, mock_redis):
        """clear_touches deletes the touches key for the marker."""
        mock_redis.delete = AsyncMock(return_value=1)

        await clear_touches(mock_redis, "silo-1", "marker-99")

        mock_redis.delete.assert_awaited_once_with("touches:silo-1:marker-99")

    @pytest.mark.asyncio
    async def test_clears_all_sessions(self, mock_redis):
        """Clearing removes the whole key (all sessions) not individual members."""
        mock_redis.delete = AsyncMock(return_value=1)

        await clear_touches(mock_redis, "silo-2", "marker-7")

        # Should call delete (not zrem) to wipe all sessions at once
        mock_redis.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_redis_error_is_swallowed(self, mock_redis):
        """Failures in clear_touches do not propagate."""
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("redis gone"))

        # Should not raise
        await clear_touches(mock_redis, "silo-1", "marker-1")
