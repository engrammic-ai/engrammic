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
        """Add a node ID to a session's node set.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.
            node_id: Context node ID to associate.

        Returns:
            True if node was added (not already present).

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Get all node IDs associated with a session.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.

        Returns:
            List of node IDs.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Remove a node ID from a session's node set.

        Args:
            silo_id: Silo identifier for key namespacing.
            session_id: Unique session identifier.
            node_id: Context node ID to remove.

        Returns:
            True if node was removed.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Set a cache value.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Optional TTL.

        Returns:
            True if successful.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Set a cache value only if the key does not exist.

        Args:
            key: Cache key.
            value: Value to store.
            ttl_seconds: Optional TTL.

        Returns:
            True if key was set (did not exist), False if key already exists.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Get a cache value.

        Args:
            key: Cache key.

        Returns:
            Value or None if not found.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Set multiple cache values in one pipeline roundtrip.

        Raises:
            RedisOperationError: If the operation fails.
        """
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
        """Get multiple cache values in one roundtrip.

        Args:
            keys: List of cache keys.

        Returns:
            List of values (None for missing keys), same order as input.

        Raises:
            RedisOperationError: If the operation fails.
        """
        start = time.perf_counter()
        try:
            result: list[bytes | None] = await self._redis.mget(keys)
            return result
        except (RedisConnectionError, RedisError) as e:
            logger.error("redis_mget_failed", key_count=len(keys), error=str(e))
            raise RedisOperationError(f"Failed to mget cache values: {e}") from e
        finally:
            record_db_query("redis.mget", (time.perf_counter() - start) * 1000)

    async def delete(self, key: str) -> bool:
        """Delete a cache key.

        Args:
            key: Cache key.

        Returns:
            True if key existed and was deleted.

        Raises:
            RedisOperationError: If the operation fails.
        """
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

    async def close(self) -> None:
        """Close the Redis connection pool."""
        try:
            await self._redis.aclose()
        except Exception as e:
            logger.warning("redis_close_error", error=str(e))
