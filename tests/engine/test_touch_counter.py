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
    """Mock redis.asyncio.Redis with pipeline support."""
    redis = AsyncMock()

    pipe = AsyncMock()
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.zremrangebyscore = MagicMock(return_value=pipe)
    pipe.zrangebyscore = MagicMock(return_value=pipe)
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
        # pipeline returns: [zadd_result, zremrangebyscore_result, zrangebyscore_result]
        # zrangebyscore returns one member for session-a
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[1, 0, [b"session-a:1000000000000"]]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 1

    @pytest.mark.asyncio
    async def test_multiple_touches_same_session_increment_count(self, mock_redis):
        """Repeated touches from the same session accumulate (2, 3, etc.)."""
        now_ms = 2_000_000

        # Simulate state after 2nd touch: two members for session-a
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[
                1,
                0,
                [b"session-a:1999000000000", b"session-a:2000000000000"],
            ]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 2

    @pytest.mark.asyncio
    async def test_third_touch_returns_three(self, mock_redis):
        """Third touch from same session returns 3."""
        now_ms = 3_000_000

        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[
                1,
                0,
                [
                    b"session-a:1000000000000",
                    b"session-a:2000000000000",
                    b"session-a:3000000000000",
                ],
            ]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 3

    @pytest.mark.asyncio
    async def test_different_sessions_counted_independently(self, mock_redis):
        """Members from other sessions are not counted for the queried session."""
        now_ms = 3_000_000

        # Both session-a and session-b have members in the set, but only
        # session-a's count is returned for session-a.
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[
                1,
                0,
                [
                    b"session-a:1000000000000",
                    b"session-a:2000000000000",
                    b"session-b:3000000000000",
                ],
            ]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        # Only 2 of the 3 members belong to session-a
        assert result == 2

    @pytest.mark.asyncio
    async def test_decayed_touch_returns_zero(self, mock_redis):
        """After all touches decay, zrangebyscore returns empty list and count is 0."""
        now_ms = 4_000_000
        # zrangebyscore returns empty after prune
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, 1, []])

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
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[1, 0, [b"sess-1:5000000000000"]]
        )

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

    @pytest.mark.asyncio
    async def test_member_uses_session_prefix(self, mock_redis):
        """Member added to sorted set starts with session_id: prefix."""
        now_ms = 6_000_000
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[1, 0, [b"session-a:6000000000000"]]
        )

        pipe = mock_redis._mock_pipe
        zadd_calls: list[tuple[object, ...]] = []
        original_zadd = pipe.zadd

        def capture_zadd(*args: object, **kwargs: object) -> object:
            zadd_calls.append(args)
            return original_zadd(*args, **kwargs)

        pipe.zadd = MagicMock(side_effect=capture_zadd)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            await record_touch(mock_redis, "silo-1", "marker-1", "session-a")

        assert zadd_calls, "zadd was never called"
        # Second arg to zadd is the mapping dict {member: score}
        member_map: dict[str, object] = zadd_calls[0][1]
        members = list(member_map.keys())
        assert len(members) == 1
        assert members[0].startswith("session-a:")


# ---------------------------------------------------------------------------
# get_touch_count
# ---------------------------------------------------------------------------


class TestGetTouchCount:
    @pytest.mark.asyncio
    async def test_active_touch_returns_one(self, mock_redis):
        """Session with one active member returns 1."""
        now_ms = 10_000_000
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[0, [b"session-a:10000000000000"]]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 1

    @pytest.mark.asyncio
    async def test_multiple_active_touches_returns_correct_count(self, mock_redis):
        """Session with multiple active members returns correct cumulative count."""
        now_ms = 10_000_000
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[
                0,
                [
                    b"session-a:9000000000000",
                    b"session-a:9500000000000",
                    b"session-a:10000000000000",
                ],
            ]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 3

    @pytest.mark.asyncio
    async def test_no_touch_returns_zero(self, mock_redis):
        """Session not in set returns 0."""
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, []])

        result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-new")

        assert result == 0

    @pytest.mark.asyncio
    async def test_other_session_members_not_counted(self, mock_redis):
        """Members from other sessions are not counted."""
        now_ms = 20_000_000
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[
                0,
                [
                    b"session-a:19000000000000",
                    b"session-b:19500000000000",
                    b"session-b:20000000000000",
                ],
            ]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(
                mock_redis, "silo-1", "marker-1", "session-a"
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_after_decay_count_drops(self, mock_redis):
        """After decay window, old touches are pruned and count drops."""
        now_ms = 20_000_000
        # Prune removed old entries; only one remains
        mock_redis._mock_pipe.execute = AsyncMock(
            return_value=[2, [b"session-a:20000000000000"]]
        )

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            result = await get_touch_count(
                mock_redis,
                "silo-1",
                "marker-1",
                "session-a",
                decay_window_ms=1_000,
            )

        assert result == 1

    @pytest.mark.asyncio
    async def test_redis_error_returns_zero(self, mock_redis):
        """Redis failure is swallowed and returns 0."""
        mock_redis._mock_pipe.execute = AsyncMock(side_effect=ConnectionError("timeout"))

        result = await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert result == 0

    @pytest.mark.asyncio
    async def test_prune_called_on_read(self, mock_redis):
        """get_touch_count calls zremrangebyscore to prune on reads."""
        now_ms = 10_000_000
        mock_redis._mock_pipe.execute = AsyncMock(return_value=[0, []])

        pipe = mock_redis._mock_pipe
        zremrange_calls: list[tuple[object, ...]] = []
        original = pipe.zremrangebyscore

        def capture(*args: object, **kwargs: object) -> object:
            zremrange_calls.append(args)
            return original(*args, **kwargs)

        pipe.zremrangebyscore = MagicMock(side_effect=capture)

        with patch("context_service.engine.touch_counter._now_ms", return_value=now_ms):
            await get_touch_count(mock_redis, "silo-1", "marker-1", "session-a")

        assert zremrange_calls, "zremrangebyscore was not called on read"


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
