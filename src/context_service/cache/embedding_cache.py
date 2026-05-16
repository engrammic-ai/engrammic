"""Redis-backed cache for embedding vectors."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.utils.json import dumps, loads

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class EmbeddingCache:
    """Cache embedding vectors in Redis to avoid duplicate embedding API calls."""

    KEY_PREFIX = "cache:embed"

    def __init__(self, redis: RedisClient, ttl: int | None = None) -> None:
        self._redis = redis
        self._ttl = ttl if ttl is not None else get_settings().embedding_cache_ttl

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _key(self, text: str, task: str) -> str:
        return f"{self.KEY_PREFIX}:{task}:{self._hash_text(text)}"

    async def get(self, text: str, task: str) -> list[float] | None:
        """Get a cached embedding vector. Returns None on miss or error."""
        try:
            data = await self._redis.get(self._key(text, task))
            if data is None:
                return None
            result: list[float] = loads(data)
            return result
        except Exception as e:
            logger.debug("embedding_cache_get_error", error=str(e))
            return None

    async def set(self, text: str, task: str, vector: list[float]) -> None:
        """Cache an embedding vector. Fire-and-forget on error."""
        try:
            data = dumps(vector)
            await self._redis.set(self._key(text, task), data, ttl_seconds=self._ttl)
        except Exception as e:
            logger.debug("embedding_cache_set_error", error=str(e))
