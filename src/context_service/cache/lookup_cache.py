"""Redis-backed cache for lookup query results."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class LookupCache:
    """Cache semantic lookup results in Redis to avoid repeating full pipeline.

    Cache keys are silo-scoped (disposable; no migration script needed on key
    changes).
    """

    KEY_PREFIX = "cache:lookup"

    def __init__(self, redis: RedisClient, ttl: int = 300) -> None:
        self._redis = redis
        self._ttl = ttl

    @staticmethod
    def _hash_query(query: str, filters: dict[str, Any]) -> str:
        raw = dumps({"q": query, "f": filters}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _key(self, silo_id: str, query: str, filters: dict[str, Any]) -> str:
        return f"{self.KEY_PREFIX}:{silo_id}:{self._hash_query(query, filters)}"

    async def get(
        self, silo_id: str, query: str, filters: dict[str, Any]
    ) -> list[dict[str, Any]] | None:
        """Get cached lookup results. Returns None on miss or error."""
        try:
            data = await self._redis.get(self._key(silo_id, query, filters))
            if data is None:
                return None
            result: list[dict[str, Any]] = loads(data)
            return result
        except Exception as e:
            logger.debug("lookup_cache_get_error", error=str(e))
            return None

    async def set(
        self,
        silo_id: str,
        query: str,
        filters: dict[str, Any],
        results: list[dict[str, Any]],
    ) -> None:
        """Cache lookup results. Fire-and-forget on error."""
        try:
            data = dumps(results)
            await self._redis.set(self._key(silo_id, query, filters), data, ttl_seconds=self._ttl)
        except Exception as e:
            logger.debug("lookup_cache_set_error", error=str(e))

    async def invalidate_silo(self, silo_id: str) -> None:
        """Invalidate all lookup cache entries for a silo via SCAN."""
        pattern = f"{self.KEY_PREFIX}:{silo_id}:*"
        try:
            cursor: int = 0
            while True:
                cursor, keys = await self._redis._redis.scan(
                    cursor=cursor, match=pattern, count=100
                )
                if keys:
                    await self._redis._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug("lookup_cache_invalidate_silo_error", error=str(e))
