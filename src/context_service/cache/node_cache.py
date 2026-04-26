"""Redis-backed cache for context nodes."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class NodeCache:
    """Cache context nodes in Redis.

    Cache keys are silo-scoped (disposable; no migration script needed on key
    changes).

    Supports two calling conventions:
    - Domain-specific: get(silo_id, node_id), set(silo_id, node_id, data)
    - Generic key-value: get(key), set(key, value) -- used by ContextService
    """

    KEY_PREFIX = "cache:node"

    def __init__(self, redis: RedisClient, ttl: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl

    def _key(self, silo_id: str, node_id: str) -> str:
        return f"{self.KEY_PREFIX}:{silo_id}:{node_id}"

    async def get(self, key_or_silo: str, node_id: str | None = None) -> Any:
        """Get a cached value.

        Two calling conventions:
        - get(key) -> raw bytes or None
        - get(silo_id, node_id) -> parsed dict or None
        """
        try:
            if node_id is not None:
                data = await self._redis.get(self._key(key_or_silo, node_id))
                if data is None:
                    return None
                result: dict[str, Any] = json.loads(data)
                return result
            return await self._redis.get(key_or_silo)
        except Exception as e:
            logger.debug("node_cache_get_error", error=str(e))
            return None

    async def set(
        self,
        key_or_silo: str,
        value_or_node_id: str,
        node_data: str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache a value.

        Two calling conventions:
        - set(key, value) -> store raw string
        - set(silo_id, node_id, json_data) -> store with domain key

        ttl_seconds overrides the instance-level TTL for this write only.
        """
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        try:
            if node_data is not None:
                await self._redis.set(
                    self._key(key_or_silo, value_or_node_id),
                    node_data,
                    ttl_seconds=ttl,
                )
            else:
                await self._redis.set(key_or_silo, value_or_node_id, ttl_seconds=ttl)
        except Exception as e:
            logger.debug("node_cache_set_error", error=str(e))

    async def delete(self, key_or_silo: str, node_id: str | None = None) -> None:
        """Remove from cache.

        Two calling conventions:
        - delete(key) -> delete by raw key
        - delete(silo_id, node_id) -> delete by domain key
        """
        try:
            if node_id is not None:
                await self._redis.delete(self._key(key_or_silo, node_id))
            else:
                await self._redis.delete(key_or_silo)
        except Exception as e:
            logger.debug("node_cache_delete_error", error=str(e))

    async def batch_get(self, silo_id: str, node_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Get multiple nodes from cache using MGET."""
        if not node_ids:
            return {}

        keys = [self._key(silo_id, nid) for nid in node_ids]
        try:
            values: list[bytes | None] = await self._redis.mget(keys)
            result: dict[str, dict[str, Any]] = {}
            for nid, val in zip(node_ids, values, strict=True):
                if val is not None:
                    with contextlib.suppress(json.JSONDecodeError, TypeError):
                        result[nid] = json.loads(val)
            return result
        except Exception as e:
            logger.debug("node_cache_batch_get_error", error=str(e))
            return {}
