"""Unit tests for stores/redis.py — no live Redis instance required.

Uses unittest.mock.AsyncMock to simulate async Redis operations so every
code path in RedisClient and create_redis_pool can be exercised in isolation.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from context_service.extraction.filter import circuit_breaker
from context_service.stores.redis import RedisClient, create_redis_pool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cb_registry() -> None:
    """Reset the CB registry between tests to prevent circuit state bleed."""
    circuit_breaker._registry.clear()


def _make_redis_mock(**overrides: Any) -> AsyncMock:
    """Return a fully-mocked async Redis instance."""
    mock = AsyncMock()
    for attr, val in overrides.items():
        setattr(mock, attr, val)
    return mock


# ---------------------------------------------------------------------------
# create_redis_pool
# ---------------------------------------------------------------------------


class TestCreateRedisPool:
    async def test_uses_provided_settings(self) -> None:
        settings = MagicMock()
        settings.redis_url = "redis://localhost:6379/0"
        settings.redis_max_connections = 10

        with (
            patch("context_service.stores.redis.ConnectionPool") as mock_pool_cls,
            patch("context_service.stores.redis.Redis") as mock_redis_cls,
        ):
            mock_pool = MagicMock()
            mock_pool_cls.from_url.return_value = mock_pool
            mock_redis_cls.return_value = AsyncMock()

            result = await create_redis_pool(settings)

            mock_pool_cls.from_url.assert_called_once_with(
                "redis://localhost:6379/0",
                max_connections=10,
                decode_responses=False,
            )
            mock_redis_cls.assert_called_once_with(connection_pool=mock_pool)
            assert result is mock_redis_cls.return_value

    async def test_falls_back_to_default_settings(self) -> None:
        fake_settings = MagicMock()
        fake_settings.redis_url = "redis://localhost:6379/0"
        fake_settings.redis_max_connections = 50

        with (
            patch("context_service.stores.redis.get_settings", return_value=fake_settings),
            patch("context_service.stores.redis.ConnectionPool") as mock_pool_cls,
            patch("context_service.stores.redis.Redis"),
        ):
            mock_pool_cls.from_url.return_value = MagicMock()
            await create_redis_pool()  # no settings arg
            mock_pool_cls.from_url.assert_called_once()
            call_url = mock_pool_cls.from_url.call_args[0][0]
            assert call_url == "redis://localhost:6379/0"

    async def test_connection_pool_decode_responses_is_false(self) -> None:
        """decode_responses must be False — RedisClient decodes bytes itself."""
        settings = MagicMock()
        settings.redis_url = "redis://localhost:6379/1"
        settings.redis_max_connections = 5

        with (
            patch("context_service.stores.redis.ConnectionPool") as mock_pool_cls,
            patch("context_service.stores.redis.Redis"),
        ):
            mock_pool_cls.from_url.return_value = MagicMock()
            await create_redis_pool(settings)
            kwargs = mock_pool_cls.from_url.call_args[1]
            assert kwargs["decode_responses"] is False


# ---------------------------------------------------------------------------
# RedisClient — initialization
# ---------------------------------------------------------------------------


class TestRedisClientInit:
    def test_stores_redis_instance(self) -> None:
        redis_mock = _make_redis_mock()
        client = RedisClient(redis_mock)
        assert client._redis is redis_mock

    def test_session_key_format(self) -> None:
        assert RedisClient._session_key("silo-1", "sess-abc") == "session:silo-1:sess-abc"

    def test_session_nodes_key_format(self) -> None:
        assert (
            RedisClient._session_nodes_key("silo-1", "sess-abc") == "session:silo-1:sess-abc:nodes"
        )


# ---------------------------------------------------------------------------
# RedisClient.health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_returns_true_on_ping_success(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.ping.return_value = True
        client = RedisClient(redis_mock)
        assert await client.health_check() is True

    async def test_returns_false_on_connection_error(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.ping.side_effect = RedisConnectionError("refused")
        client = RedisClient(redis_mock)
        assert await client.health_check() is False

    async def test_returns_false_on_generic_exception(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.ping.side_effect = RuntimeError("unexpected")
        client = RedisClient(redis_mock)
        assert await client.health_check() is False


# ---------------------------------------------------------------------------
# RedisClient — session operations
# ---------------------------------------------------------------------------


class TestSetSession:
    async def test_stores_json_encoded_bytes(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = True
        client = RedisClient(redis_mock)

        result = await client.set_session("silo-1", "sess-1", {"k": "v"}, ttl_seconds=3600)

        assert result is True
        redis_mock.set.assert_called_once()
        call_key, call_val = redis_mock.set.call_args[0]
        assert call_key == "session:silo-1:sess-1"
        assert isinstance(call_val, bytes)
        assert b'"k"' in call_val

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.set.side_effect = RedisError("write failed")
        client = RedisClient(redis_mock)

        result = await client.set_session("silo-1", "sess-1", {})
        assert result is False

    async def test_degrades_on_connection_error(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.side_effect = RedisConnectionError("conn lost")
        client = RedisClient(redis_mock)

        result = await client.set_session("silo-1", "sess-1", {})
        assert result is False


class TestGetSession:
    async def test_returns_none_when_key_missing(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.get.return_value = None
        client = RedisClient(redis_mock)

        assert await client.get_session("silo-1", "sess-1") is None

    async def test_parses_json_bytes(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.get.return_value = b'{"agent_id": "agent-x"}'
        client = RedisClient(redis_mock)

        result = await client.get_session("silo-1", "sess-1")
        assert result == {"agent_id": "agent-x"}

    async def test_returns_none_on_corrupt_json(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.get.return_value = b"not-json{"
        client = RedisClient(redis_mock)

        assert await client.get_session("silo-1", "sess-1") is None

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to None, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.get.side_effect = RedisError("timeout")
        client = RedisClient(redis_mock)

        result = await client.get_session("silo-1", "sess-1")
        assert result is None


def _make_pipeline_mock(execute_return: Any = None, execute_side_effect: Any = None) -> MagicMock:
    """Build a pipeline mock where pipeline() is sync but execute() is async."""
    pipeline_mock = MagicMock()
    if execute_side_effect is not None:
        pipeline_mock.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        pipeline_mock.execute = AsyncMock(return_value=execute_return)
    return pipeline_mock


class TestDeleteSession:
    async def test_returns_true_when_session_existed(self) -> None:
        redis_mock = _make_redis_mock()
        pipeline_mock = _make_pipeline_mock(execute_return=[1, 0])
        redis_mock.pipeline = MagicMock(return_value=pipeline_mock)
        client = RedisClient(redis_mock)

        assert await client.delete_session("silo-1", "sess-1") is True

    async def test_returns_false_when_session_missing(self) -> None:
        redis_mock = _make_redis_mock()
        pipeline_mock = _make_pipeline_mock(execute_return=[0, 0])
        redis_mock.pipeline = MagicMock(return_value=pipeline_mock)
        client = RedisClient(redis_mock)

        assert await client.delete_session("silo-1", "sess-1") is False

    async def test_degrades_on_pipeline_failure(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        pipeline_mock = _make_pipeline_mock(execute_side_effect=RedisError("pipeline error"))
        redis_mock.pipeline = MagicMock(return_value=pipeline_mock)
        client = RedisClient(redis_mock)

        result = await client.delete_session("silo-1", "sess-1")
        assert result is False


# ---------------------------------------------------------------------------
# RedisClient — session node set operations
# ---------------------------------------------------------------------------


class TestSessionNodes:
    async def test_add_node_returns_true_when_new(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.sadd.return_value = 1
        client = RedisClient(redis_mock)

        assert await client.add_session_node("silo-1", "sess-1", "node-abc") is True

    async def test_add_node_returns_false_when_already_present(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.sadd.return_value = 0
        client = RedisClient(redis_mock)

        assert await client.add_session_node("silo-1", "sess-1", "node-abc") is False

    async def test_add_node_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.sadd.side_effect = RedisConnectionError("no conn")
        client = RedisClient(redis_mock)

        result = await client.add_session_node("silo-1", "sess-1", "node-abc")
        assert result is False

    async def test_get_session_nodes_decodes_members(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.smembers.return_value = {b"node-1", b"node-2"}
        client = RedisClient(redis_mock)

        nodes = await client.get_session_nodes("silo-1", "sess-1")
        assert set(nodes) == {"node-1", "node-2"}

    async def test_get_session_nodes_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to [], not raise.
        redis_mock = _make_redis_mock()
        redis_mock.smembers.side_effect = RedisError("smembers failed")
        client = RedisClient(redis_mock)

        result = await client.get_session_nodes("silo-1", "sess-1")
        assert result == []

    async def test_remove_node_returns_true_when_removed(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.srem.return_value = 1
        client = RedisClient(redis_mock)

        assert await client.remove_session_node("silo-1", "sess-1", "node-1") is True

    async def test_remove_node_returns_false_when_absent(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.srem.return_value = 0
        client = RedisClient(redis_mock)

        assert await client.remove_session_node("silo-1", "sess-1", "node-1") is False

    async def test_remove_node_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.srem.side_effect = RedisConnectionError("srem fail")
        client = RedisClient(redis_mock)

        result = await client.remove_session_node("silo-1", "sess-1", "node-1")
        assert result is False


# ---------------------------------------------------------------------------
# RedisClient — generic cache operations
# ---------------------------------------------------------------------------


class TestCacheSet:
    async def test_set_with_str_value_encodes_to_bytes(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = True
        client = RedisClient(redis_mock)

        result = await client.set("my-key", "hello", ttl_seconds=60)

        assert result is True
        _key, val = redis_mock.set.call_args[0]
        assert val == b"hello"

    async def test_set_with_bytes_value_passes_through(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = True
        client = RedisClient(redis_mock)

        await client.set("my-key", b"\x00\x01")
        _key, val = redis_mock.set.call_args[0]
        assert val == b"\x00\x01"

    async def test_set_without_ttl_passes_none(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = True
        client = RedisClient(redis_mock)

        await client.set("k", "v")
        kwargs = redis_mock.set.call_args[1]
        assert kwargs.get("ex") is None

    async def test_set_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.set.side_effect = RedisError("write error")
        client = RedisClient(redis_mock)

        result = await client.set("k", "v")
        assert result is False


class TestCacheSetNx:
    async def test_returns_true_when_key_was_set(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = True  # truthy means key was absent
        client = RedisClient(redis_mock)

        assert await client.set_nx("k", "v") is True

    async def test_returns_false_when_key_already_exists(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.set.return_value = None  # None means key already existed
        client = RedisClient(redis_mock)

        assert await client.set_nx("k", "v") is False

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.set.side_effect = RedisError("nx error")
        client = RedisClient(redis_mock)

        result = await client.set_nx("k", "v")
        assert result is False


class TestCacheGet:
    async def test_returns_bytes_value(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.get.return_value = b"cached"
        client = RedisClient(redis_mock)

        assert await client.get("k") == b"cached"

    async def test_returns_none_for_missing_key(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.get.return_value = None
        client = RedisClient(redis_mock)

        assert await client.get("missing") is None

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to None, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.get.side_effect = RedisConnectionError("conn error")
        client = RedisClient(redis_mock)

        result = await client.get("k")
        assert result is None


class TestCacheMget:
    async def test_returns_list_preserving_none_for_missing(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.mget.return_value = [b"v1", None, b"v3"]
        client = RedisClient(redis_mock)

        result = await client.mget(["k1", "k2", "k3"])
        assert result == [b"v1", None, b"v3"]

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to all-None list, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.mget.side_effect = RedisError("mget fail")
        client = RedisClient(redis_mock)

        result = await client.mget(["k1", "k2"])
        assert result == [None, None]


class TestCacheDelete:
    async def test_returns_true_when_key_deleted(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.delete.return_value = 1
        client = RedisClient(redis_mock)

        assert await client.delete("k") is True

    async def test_returns_false_when_key_absent(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.delete.return_value = 0
        client = RedisClient(redis_mock)

        assert await client.delete("missing") is False

    async def test_degrades_on_redis_error(self) -> None:
        # Redis is an optimization layer; errors degrade to False, not raise.
        redis_mock = _make_redis_mock()
        redis_mock.delete.side_effect = RedisConnectionError("delete fail")
        client = RedisClient(redis_mock)

        result = await client.delete("k")
        assert result is False


# ---------------------------------------------------------------------------
# RedisClient.xadd
# ---------------------------------------------------------------------------


class TestXadd:
    async def test_returns_entry_id_as_string(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.return_value = b"1234-0"
        client = RedisClient(redis_mock)

        result = await client.xadd("stream:events", {"event": "read", "silo": "s1"})
        assert result == "1234-0"

    async def test_encodes_string_fields_to_bytes(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.return_value = b"5678-0"
        client = RedisClient(redis_mock)

        await client.xadd("stream:events", {"k": "v"})
        call_fields = redis_mock.xadd.call_args[0][1]
        # keys and values must be bytes after encoding
        assert b"k" in call_fields
        assert call_fields[b"k"] == b"v"

    async def test_passes_maxlen_when_provided(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.return_value = b"1-0"
        client = RedisClient(redis_mock)

        await client.xadd("s", {"f": "v"}, maxlen=100)
        kwargs = redis_mock.xadd.call_args[1]
        assert kwargs["maxlen"] == 100
        assert kwargs["approximate"] is True

    async def test_no_maxlen_omits_maxlen_kwarg(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.return_value = b"1-0"
        client = RedisClient(redis_mock)

        await client.xadd("s", {"f": "v"})
        # called without maxlen/approximate kwargs
        kwargs = redis_mock.xadd.call_args[1]
        assert "maxlen" not in kwargs

    async def test_returns_none_on_redis_error_best_effort(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.side_effect = RedisConnectionError("stream unavailable")
        client = RedisClient(redis_mock)

        result = await client.xadd("s", {"f": "v"})
        assert result is None

    async def test_returns_none_on_generic_redis_error(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.xadd.side_effect = RedisError("write err")
        client = RedisClient(redis_mock)

        assert await client.xadd("s", {"f": "v"}) is None


# ---------------------------------------------------------------------------
# RedisClient.incr_with_expire
# ---------------------------------------------------------------------------


class TestIncrWithExpire:
    async def test_increments_and_returns_count(self) -> None:
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(return_value=5)

        client = RedisClient(mock_redis)
        result = await client.incr_with_expire("test:key", 60)

        assert result == 5
        mock_redis.eval.assert_called_once()
        call_args = mock_redis.eval.call_args
        assert call_args[0][1] == 1  # number of keys
        assert call_args[0][2] == "test:key"
        assert call_args[0][3] == 60  # ttl

    async def test_returns_zero_on_circuit_open(self) -> None:
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(side_effect=RedisConnectionError("connection refused"))

        client = RedisClient(mock_redis)
        # The guard_degrade should catch and return 0
        result = await client.incr_with_expire("test:key", 60)
        assert result == 0

    async def test_first_increment_sets_ttl(self) -> None:
        mock_redis = _make_redis_mock()
        mock_redis.eval = AsyncMock(return_value=1)

        client = RedisClient(mock_redis)
        result = await client.incr_with_expire("test:key", 3600)

        assert result == 1
        assert mock_redis.eval.called


# ---------------------------------------------------------------------------
# RedisClient.close
# ---------------------------------------------------------------------------


class TestClose:
    async def test_calls_aclose_on_underlying_redis(self) -> None:
        redis_mock = _make_redis_mock()
        client = RedisClient(redis_mock)

        await client.close()
        redis_mock.aclose.assert_called_once()

    async def test_swallows_exception_on_close_error(self) -> None:
        redis_mock = _make_redis_mock()
        redis_mock.aclose.side_effect = Exception("close error")
        client = RedisClient(redis_mock)

        # should not raise
        await client.close()
