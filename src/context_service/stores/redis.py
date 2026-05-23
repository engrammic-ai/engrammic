"""Redis client for session management and caching.

Uses redis.asyncio with hiredis for performance.
"""

from __future__ import annotations

import time
from typing import Any, cast

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import RedisError

from context_service.config.logging import get_logger
from context_service.config.settings import Settings, get_settings
from context_service.engine.storage_circuit import STORE_REDIS, guard_degrade
from context_service.telemetry.metrics import record_db_query
from context_service.utils.json import JSONDecodeError, dumps, loads

logger = get_logger(__name__)


class RedisOperationError(Exception):
    """Raised when a Redis operation fails."""


async def create_redis_pool(settings: Settings | None = None) -> Redis[bytes]:  # type: ignore[type-arg]
    """Create an async Redis connection pool.

    Args:
        settings: Application settings. Uses default settings if not provided.

    Returns:
        Redis client with connection pool.
    """
    if settings is None:
        settings = get_settings()

    pool = ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=False,
    )

    return Redis(connection_pool=pool)


class RedisClient:
    """High-level Redis client for session and cache operations."""

    def __init__(self, redis: Redis[bytes]) -> None:  # type: ignore[type-arg]
        """Initialize the client with a Redis connection.

        Args:
            redis: Redis async client instance.
        """
        self._redis = redis

    @staticmethod
    def _session_key(silo_id: str, session_id: str) -> str:
        """Build a silo-scoped session key."""
        return f"session:{silo_id}:{session_id}"

    @staticmethod
    def _session_nodes_key(silo_id: str, session_id: str) -> str:
        """Build a silo-scoped session nodes key."""
        return f"session:{silo_id}:{session_id}:nodes"

    async def health_check(self) -> bool:
        """Check if Redis is reachable.

        Returns:
            True if healthy, False otherwise.
        """
        start = time.perf_counter()
        try:
            result = await self._redis.ping()  # type: ignore[misc]
            return bool(result)
        except RedisConnectionError:
            logger.warning("redis_health_check_failed", reason="connection_error")
            return False
        except Exception as e:
            logger.warning("redis_health_check_failed", error=str(e))
            return False
        finally:
            record_db_query("redis.health_check", (time.perf_counter() - start) * 1000)

    # Session operations

    async def set_session(
        self,
        silo_id: str,
        session_id: str,
        data: dict[str, Any],
        ttl_seconds: int = 86400,
    ) -> bool:
        """Store session data.

        Returns False if the Redis circuit is open (degrade).
        """
        return await guard_degrade(
            STORE_REDIS, self._set_session_impl(silo_id, session_id, data, ttl_seconds), False
        )

    async def _set_session_impl(
        self,
        silo_id: str,
        session_id: str,
        data: dict[str, Any],
        ttl_seconds: int = 86400,
    ) -> bool:
        """Store session data.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.
            data: Session metadata as dictionary.
            ttl_seconds: Time to live in seconds (default 24 hours).

        Returns:
            True if successful.

        Raises:
            RedisOperationError: If the operation fails.
        """
        key = self._session_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            await self._redis.set(key, dumps(data).encode(), ex=ttl_seconds)
            return True
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_set_session_failed", session_id=session_id, error=str(e))
            raise RedisOperationError(f"Failed to store session: {e}") from e
        finally:
            record_db_query("redis.set_session", (time.perf_counter() - start) * 1000)

    async def get_session(self, silo_id: str, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data; returns None if circuit is open (degrade)."""
        return await guard_degrade(STORE_REDIS, self._get_session_impl(silo_id, session_id), None)

    async def _get_session_impl(self, silo_id: str, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.

        Returns:
            Session data or None if not found or corrupted.
        """
        key = self._session_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            data: bytes | None = await self._redis.get(key)
            if data is None:
                return None
            parsed: dict[str, Any] = loads(data.decode())
            return parsed
        except JSONDecodeError as e:
            logger.error("redis_session_corrupted", session_id=session_id, error=str(e))
            return None
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_get_session_failed", session_id=session_id, error=str(e))
            raise RedisOperationError(f"Failed to retrieve session: {e}") from e
        finally:
            record_db_query("redis.get_session", (time.perf_counter() - start) * 1000)

    async def delete_session(self, silo_id: str, session_id: str) -> bool:
        """Delete a session; returns False if circuit is open (degrade)."""
        return await guard_degrade(
            STORE_REDIS, self._delete_session_impl(silo_id, session_id), False
        )

    async def _delete_session_impl(self, silo_id: str, session_id: str) -> bool:
        """Delete a session and its associated nodes.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.

        Returns:
            True if session existed and was deleted.

        Raises:
            RedisOperationError: If the operation fails.
        """
        session_key = self._session_key(silo_id, session_id)
        nodes_key = self._session_nodes_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            pipeline = self._redis.pipeline()
            pipeline.delete(session_key)
            pipeline.delete(nodes_key)
            results: list[Any] = await pipeline.execute()
            return bool(results[0])
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_delete_session_failed", session_id=session_id, error=str(e))
            raise RedisOperationError(f"Failed to delete session: {e}") from e
        finally:
            record_db_query("redis.delete_session", (time.perf_counter() - start) * 1000)

    async def add_session_node(self, silo_id: str, session_id: str, node_id: str) -> bool:
        """Add a node ID to a session's node set; returns False if circuit open."""
        return await guard_degrade(
            STORE_REDIS, self._add_session_node_impl(silo_id, session_id, node_id), False
        )

    async def _add_session_node_impl(self, silo_id: str, session_id: str, node_id: str) -> bool:
        key = self._session_nodes_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            result = await self._redis.sadd(key, node_id.encode())  # type: ignore[misc]
            return bool(result)
        except (RedisConnectionError, RedisError) as e:
            logger.error(
                "redis_add_session_node_failed",
                session_id=session_id,
                node_id=node_id,
                error=str(e),
            )
            raise RedisOperationError(f"Failed to add session node: {e}") from e
        finally:
            record_db_query("redis.add_session_node", (time.perf_counter() - start) * 1000)

    async def get_session_nodes(self, silo_id: str, session_id: str) -> list[str]:
        """Get session node IDs; returns [] if circuit open."""
        return await guard_degrade(
            STORE_REDIS, self._get_session_nodes_impl(silo_id, session_id), []
        )

    async def _get_session_nodes_impl(self, silo_id: str, session_id: str) -> list[str]:
        key = self._session_nodes_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            members = await self._redis.smembers(key)  # type: ignore[misc]
            return [m.decode() for m in members]
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_get_session_nodes_failed", session_id=session_id, error=str(e))
            raise RedisOperationError(f"Failed to get session nodes: {e}") from e
        finally:
            record_db_query("redis.get_session_nodes", (time.perf_counter() - start) * 1000)

    async def remove_session_node(self, silo_id: str, session_id: str, node_id: str) -> bool:
        """Remove a session node; returns False if circuit open."""
        return await guard_degrade(
            STORE_REDIS, self._remove_session_node_impl(silo_id, session_id, node_id), False
        )

    async def _remove_session_node_impl(self, silo_id: str, session_id: str, node_id: str) -> bool:
        key = self._session_nodes_key(silo_id, session_id)
        start = time.perf_counter()
        try:
            result = await self._redis.srem(key, node_id.encode())  # type: ignore[misc]
            return bool(result)
        except (RedisConnectionError, RedisError) as e:
            logger.error(
                "redis_remove_session_node_failed",
                session_id=session_id,
                node_id=node_id,
                error=str(e),
            )
            raise RedisOperationError(f"Failed to remove session node: {e}") from e
        finally:
            record_db_query("redis.remove_session_node", (time.perf_counter() - start) * 1000)

    # Generic cache operations

    async def set(
        self,
        key: str,
        value: str | bytes,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Set a cache value; returns False if circuit open."""
        return await guard_degrade(STORE_REDIS, self._set_impl(key, value, ttl_seconds), False)

    async def _set_impl(self, key: str, value: str | bytes, ttl_seconds: int | None = None) -> bool:
        if isinstance(value, str):
            value = value.encode()
        start = time.perf_counter()
        try:
            await self._redis.set(key, value, ex=ttl_seconds)
            return True
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_set_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to set cache value: {e}") from e
        finally:
            record_db_query("redis.set", (time.perf_counter() - start) * 1000)

    async def set_nx(
        self,
        key: str,
        value: str | bytes,
        ttl_seconds: int | None = None,
    ) -> bool:
        """Set a cache value only if absent; returns False if circuit open."""
        return await guard_degrade(STORE_REDIS, self._set_nx_impl(key, value, ttl_seconds), False)

    async def _set_nx_impl(
        self, key: str, value: str | bytes, ttl_seconds: int | None = None
    ) -> bool:
        if isinstance(value, str):
            value = value.encode()
        start = time.perf_counter()
        try:
            result = await self._redis.set(key, value, ex=ttl_seconds, nx=True)
            return result is not None
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_set_nx_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to set_nx cache value: {e}") from e
        finally:
            record_db_query("redis.set_nx", (time.perf_counter() - start) * 1000)

    async def get(self, key: str) -> bytes | None:
        """Get a cache value; returns None if circuit open."""
        return await guard_degrade(STORE_REDIS, self._get_impl(key), None)

    async def _get_impl(self, key: str) -> bytes | None:
        start = time.perf_counter()
        try:
            result: bytes | None = await self._redis.get(key)
            return result
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_get_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to get cache value: {e}") from e
        finally:
            record_db_query("redis.get", (time.perf_counter() - start) * 1000)

    async def mset(self, mapping: dict[str, bytes]) -> None:
        """Set multiple cache values; no-ops if circuit open."""
        await guard_degrade(STORE_REDIS, self._mset_impl(mapping), None)

    async def _mset_impl(self, mapping: dict[str, bytes]) -> None:
        start = time.perf_counter()
        try:
            pipeline = self._redis.pipeline(transaction=False)
            for key, value in mapping.items():
                pipeline.set(key, value)
            await pipeline.execute()
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_mset_failed", key_count=len(mapping), error=str(e))
            raise RedisOperationError(f"Failed to mset cache values: {e}") from e
        finally:
            record_db_query("redis.mset", (time.perf_counter() - start) * 1000)

    async def mget(self, keys: list[str]) -> list[bytes | None]:
        """Get multiple cache values; returns all-None list if circuit open."""
        default: list[bytes | None] = [None] * len(keys)
        return await guard_degrade(STORE_REDIS, self._mget_impl(keys), default)

    async def _mget_impl(self, keys: list[str]) -> list[bytes | None]:
        start = time.perf_counter()
        try:
            result: list[bytes | None] = await self._redis.mget(keys)
            return result
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_mget_failed", key_count=len(keys), error=str(e))
            raise RedisOperationError(f"Failed to mget cache values: {e}") from e
        finally:
            record_db_query("redis.mget", (time.perf_counter() - start) * 1000)

    async def incr(self, key: str) -> int:
        """Increment an integer counter at key; returns 0 if circuit open."""
        return await guard_degrade(STORE_REDIS, self._incr_impl(key), 0)

    async def _incr_impl(self, key: str) -> int:
        start = time.perf_counter()
        try:
            result: int = await self._redis.incr(key)
            return result
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_incr_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to increment key: {e}") from e
        finally:
            record_db_query("redis.incr", (time.perf_counter() - start) * 1000)

    async def delete(self, key: str) -> bool:
        """Delete a cache key; returns False if circuit open."""
        return await guard_degrade(STORE_REDIS, self._delete_impl(key), False)

    async def _delete_impl(self, key: str) -> bool:
        start = time.perf_counter()
        try:
            result = await self._redis.delete(key)
            return bool(result)
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_delete_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to delete cache value: {e}") from e
        finally:
            record_db_query("redis.delete", (time.perf_counter() - start) * 1000)

    async def xadd(
        self,
        stream_key: str,
        fields: dict[str, str | bytes],
        *,
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> str | None:
        """Append an entry to a Redis stream.

        Best-effort: connection / Redis errors are logged and swallowed,
        returning None so callers in hot paths never raise.

        Args:
            stream_key: Stream key (e.g. ``silo:{silo_id}:access_events``).
            fields: Field name -> value pairs. Strings are encoded as UTF-8.
            maxlen: Optional cap on stream length.
            approximate: When True, uses ``MAXLEN ~`` (cheap, slightly fuzzy cap).

        Returns:
            The generated entry ID on success, or None on failure.
        """
        _RedisFields = dict[
            bytes | bytearray | memoryview | str | int | float,
            bytes | bytearray | memoryview | str | int | float,
        ]
        encoded: _RedisFields = cast(
            _RedisFields,
            {
                (k.encode() if isinstance(k, str) else k): (v.encode() if isinstance(v, str) else v)
                for k, v in fields.items()
            },
        )
        start = time.perf_counter()
        try:
            if maxlen is not None:
                entry_id = await self._redis.xadd(
                    stream_key, encoded, maxlen=maxlen, approximate=approximate
                )
            else:
                entry_id = await self._redis.xadd(stream_key, encoded)
            return entry_id.decode() if isinstance(entry_id, bytes) else entry_id
        except (RedisConnectionError, RedisError) as e:
            logger.warning("redis_xadd_failed", stream_key=stream_key, error=str(e))
            return None
        finally:
            record_db_query("redis.xadd", (time.perf_counter() - start) * 1000)

    async def lrange(self, key: str, start: int, end: int) -> list[bytes]:
        """Return a range of elements from a Redis list; returns [] if circuit open."""
        default: list[bytes] = []
        return await guard_degrade(STORE_REDIS, self._lrange_impl(key, start, end), default)

    async def _lrange_impl(self, key: str, start: int, end: int) -> list[bytes]:
        t = time.perf_counter()
        try:
            result: list[bytes] = await self._redis.lrange(key, start, end)  # type: ignore[misc]
            return result
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_lrange_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to lrange: {e}") from e
        finally:
            record_db_query("redis.lrange", (time.perf_counter() - t) * 1000)

    async def list_push_trim_expire(
        self, key: str, entry: bytes, max_entries: int, ttl: int
    ) -> None:
        """Atomically lpush + ltrim + expire a bounded list. No-ops if circuit open."""
        await guard_degrade(
            STORE_REDIS, self._list_push_trim_expire_impl(key, entry, max_entries, ttl), None
        )

    async def _list_push_trim_expire_impl(
        self, key: str, entry: bytes, max_entries: int, ttl: int
    ) -> None:
        t = time.perf_counter()
        try:
            pipeline = self._redis.pipeline(transaction=False)
            pipeline.lpush(key, entry)
            pipeline.ltrim(key, 0, max_entries - 1)
            pipeline.expire(key, ttl)
            await pipeline.execute()
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_list_push_trim_expire_failed", key=key, error=str(e))
            raise RedisOperationError(f"Failed to list_push_trim_expire: {e}") from e
        finally:
            record_db_query("redis.list_push_trim_expire", (time.perf_counter() - t) * 1000)

    # Lua script for atomic INCR + EXPIRE (works on Redis 6.2+)
    # Sets TTL only on first creation (when count == 1)
    _INCR_EXPIRE_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return count
"""

    async def incr_with_expire(self, key: str, ttl_seconds: int) -> int:
        """Atomically increment a counter and set TTL on first creation.

        Uses a Lua script for true atomicity (no race between INCR and EXPIRE).
        TTL is only set when count == 1 (first increment).

        Args:
            key: Redis key to increment.
            ttl_seconds: TTL for the key (only applied on first creation).

        Returns:
            New counter value, or 0 if circuit is open (fail-open).
        """
        return await guard_degrade(STORE_REDIS, self._incr_with_expire_impl(key, ttl_seconds), 0)

    async def _incr_with_expire_impl(self, key: str, ttl_seconds: int) -> int:
        """Implementation for atomic INCR + EXPIRE via Lua."""
        start = time.perf_counter()
        try:
            result = await self._redis.eval(  # type: ignore[misc]
                self._INCR_EXPIRE_SCRIPT,
                1,  # number of keys
                key,
                ttl_seconds,
            )
            return int(result)
        except (RedisConnectionError, RedisError) as e:
            logger.warning("redis_incr_with_expire_failed", key=key, error=str(e))
            raise
        finally:
            record_db_query("redis.incr_with_expire", (time.perf_counter() - start) * 1000)

    async def close(self) -> None:
        """Close the Redis connection pool."""
        try:
            await self._redis.aclose()
        except Exception as e:
            logger.warning("redis_close_error", error=str(e))
