"""Redis-backed positive-only cache for silo ownership lookups."""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)

# No negative caching — security cost too high; failed lookups always re-check the DB.


class SiloOwnershipCache:
    """Cache successful silo-ownership validations in Redis.

    Only positive results (org_id owns silo_id) are cached. Failed lookups
    are never cached so revocations and misconfigurations surface on the
    next call instead of being masked for the TTL window.
    """

    KEY_PREFIX = "cache:silo_ownership"

    def __init__(self, redis: RedisClient, ttl: int = 90) -> None:
        self._redis = redis
        self._ttl = ttl

    def _key(self, org_id: str, silo_id: str) -> str:
        return f"{self.KEY_PREFIX}:{org_id}:{silo_id}"

    async def get(self, org_id: str, silo_id: str) -> bool | None:
        """Return True on cached-valid hit, None on miss.

        We never cache False, so this method also returns None to mean
        "no cached answer; re-check the DB".
        """
        try:
            data = await self._redis.get(self._key(org_id, silo_id))
            if data is None:
                return None
            return True
        except Exception as e:
            logger.debug("silo_ownership_cache_get_error", error=str(e))
            return None

    async def set(
        self,
        org_id: str,
        silo_id: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Mark (org_id, silo_id) as a verified-valid pair."""
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        try:
            await self._redis.set(self._key(org_id, silo_id), "1", ttl_seconds=ttl)
        except Exception as e:
            logger.debug("silo_ownership_cache_set_error", error=str(e))

    async def delete(self, org_id: str, silo_id: str) -> None:
        """Invalidate a cached ownership entry."""
        try:
            await self._redis.delete(self._key(org_id, silo_id))
        except Exception as e:
            logger.debug("silo_ownership_cache_delete_error", error=str(e))
