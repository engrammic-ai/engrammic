"""Redis-backed cache for alias resolution lookups.

Implements the _CacheReader protocol required by resolve_alias() in
context_service.extraction.alias_lookup. Keys are silo-scoped.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger
from context_service.telemetry.metrics import record_cache_hit, record_cache_miss
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)

_KEY_PREFIX = "alias"
_DEFAULT_TTL = 3600  # 1 hour — alias commitments are stable


class AliasCache:
    """Cache alias -> canonical entity mappings in Redis.

    Keys: ``alias:{silo_id}:{normalized_form}``
    Values: JSON dict with ``entity_id`` and ``canonical_name``.

    Satisfies the ``_CacheReader`` protocol used by
    :func:`context_service.extraction.alias_lookup.resolve_alias`.
    """

    def __init__(self, redis: RedisClient, ttl: int = _DEFAULT_TTL) -> None:
        self._redis = redis
        self._ttl = ttl

    def _key(self, silo_id: str, normalized_form: str) -> str:
        return f"{_KEY_PREFIX}:{silo_id}:{normalized_form}"

    async def get(self, silo_id: str, normalized_form: str) -> dict[str, Any] | None:
        """Return cached alias entry, or None on miss or error."""
        try:
            data = await self._redis.get(self._key(silo_id, normalized_form))
            if data is None:
                record_cache_miss("alias", silo_id=silo_id)
                return None
            record_cache_hit("alias", silo_id=silo_id)
            result: dict[str, Any] = loads(data)
            return result
        except Exception as exc:
            logger.debug("alias_cache_get_error", error=str(exc))
            return None

    async def set(
        self,
        silo_id: str,
        normalized_form: str,
        entity_id: str,
        canonical_name: str,
    ) -> None:
        """Cache an alias entry. Fire-and-forget on error."""
        try:
            payload = dumps({"entity_id": entity_id, "canonical_name": canonical_name})
            await self._redis.set(
                self._key(silo_id, normalized_form), payload, ttl_seconds=self._ttl
            )
        except Exception as exc:
            logger.debug("alias_cache_set_error", error=str(exc))

    async def invalidate(self, silo_id: str, normalized_form: str) -> None:
        """Remove a single alias entry."""
        try:
            await self._redis.delete(self._key(silo_id, normalized_form))
        except Exception as exc:
            logger.debug("alias_cache_invalidate_error", error=str(exc))

    async def invalidate_silo(self, silo_id: str) -> None:
        """Invalidate all alias cache entries for a silo via SCAN."""
        pattern = f"{_KEY_PREFIX}:{silo_id}:*"
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
        except Exception as exc:
            logger.debug("alias_cache_invalidate_silo_error", error=str(exc))
