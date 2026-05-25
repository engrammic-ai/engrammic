"""In-process tiered result cache using TTLCache (per-layer, version-keyed)."""

from __future__ import annotations

import hashlib
import json
import time
from typing import TYPE_CHECKING, Any

from cachetools import TTLCache

from context_service.config import get_settings
from context_service.config.logging import get_logger
from context_service.telemetry.metrics import record_cache_hit, record_cache_miss

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)

# Layer name constants used for cache selection
_LAYER_MEMORY = "memory"
_LAYER_KNOWLEDGE = "knowledge"
_LAYER_WISDOM = "wisdom"
_LAYER_INTELLIGENCE = "intelligence"


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class ResultCacheStore:
    """In-process tiered TTLCache for recall query results.

    One TTLCache per cacheable layer (memory, knowledge, wisdom).
    Intelligence layer results are never cached.
    """

    def __init__(
        self,
        memory_ttl: int | None = None,
        knowledge_ttl: int | None = None,
        wisdom_ttl: int | None = None,
        maxsize: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        cfg = get_settings().result_cache
        _enabled = enabled if enabled is not None else cfg.enabled
        _memory_ttl = memory_ttl if memory_ttl is not None else cfg.memory_ttl
        _knowledge_ttl = knowledge_ttl if knowledge_ttl is not None else cfg.knowledge_ttl
        _wisdom_ttl = wisdom_ttl if wisdom_ttl is not None else cfg.wisdom_ttl
        _maxsize = maxsize if maxsize is not None else cfg.maxsize

        if not _enabled:
            # Cache disabled: all buckets are None so get() returns None and set() is a no-op.
            self._memory_cache: (
                TTLCache[tuple[Any, ...], tuple[list[dict[str, Any]], float]] | None
            ) = None
            self._knowledge_cache: (
                TTLCache[tuple[Any, ...], tuple[list[dict[str, Any]], float]] | None
            ) = None
            self._wisdom_cache: (
                TTLCache[tuple[Any, ...], tuple[list[dict[str, Any]], float]] | None
            ) = None
            return

        # TTLCache operations are synchronous and GIL-protected; no asyncio Lock is needed.
        self._memory_cache = TTLCache(maxsize=_maxsize, ttl=_memory_ttl)
        self._knowledge_cache = TTLCache(maxsize=_maxsize, ttl=_knowledge_ttl)
        self._wisdom_cache = TTLCache(maxsize=_maxsize, ttl=_wisdom_ttl)

    def _pick_cache(
        self,
        layers: list[str] | None,
    ) -> TTLCache[tuple[Any, ...], tuple[list[dict[str, Any]], float]] | None:
        """Select the TTL bucket for the given layer set.

        Returns None if the cache is disabled, if intelligence is in layers
        (not cacheable), or if no matching bucket exists.
        Priority order:
          1. cache disabled -> None
          2. intelligence present -> no cache
          3. knowledge present OR layers is None -> knowledge cache
          4. wisdom only -> wisdom cache
          5. memory only -> memory cache
        """
        # Cache disabled: all buckets are None
        if self._knowledge_cache is None:
            return None

        if layers is not None and _LAYER_INTELLIGENCE in layers:
            return None

        if layers is None:
            return self._knowledge_cache

        layer_set = set(layers)

        if _LAYER_KNOWLEDGE in layer_set:
            return self._knowledge_cache

        if layer_set == {_LAYER_WISDOM}:
            return self._wisdom_cache

        if layer_set == {_LAYER_MEMORY}:
            return self._memory_cache

        # Mixed set without knowledge - use knowledge cache as fallback
        if _LAYER_WISDOM in layer_set or _LAYER_MEMORY in layer_set:
            return self._knowledge_cache

        return None

    @staticmethod
    def _build_key(
        effective_query: str,
        layers: list[str] | None,
        silo_id: str,
        knowledge_version: int | None,
        top_k: int,
        filters: dict[str, Any] | None,
        include_superseded: bool,
        search_mode: str,
    ) -> tuple[Any, ...]:
        query_hash = _sha256(effective_query.lower().strip())
        sorted_layers = ",".join(sorted(layers)) if layers is not None else "all"
        filters_hash = _sha256(json.dumps(filters, sort_keys=True)) if filters else "none"
        return (
            query_hash,
            sorted_layers,
            silo_id,
            knowledge_version,
            top_k,
            filters_hash,
            include_superseded,
            search_mode,
        )

    def get(
        self,
        effective_query: str,
        layers: list[str] | None,
        silo_id: str,
        knowledge_version: int | None,
        top_k: int,
        filters: dict[str, Any] | None,
        include_superseded: bool,
        search_mode: str,
    ) -> tuple[list[dict[str, Any]], float] | None:
        """Return (results, cached_at) if cached, else None."""
        cache = self._pick_cache(layers)
        if cache is None:
            return None

        key = self._build_key(
            effective_query,
            layers,
            silo_id,
            knowledge_version,
            top_k,
            filters,
            include_superseded,
            search_mode,
        )
        value = cache.get(key)
        if value is not None:
            record_cache_hit("result", silo_id=silo_id)
            return value
        record_cache_miss("result", silo_id=silo_id)
        return None

    def set(
        self,
        effective_query: str,
        layers: list[str] | None,
        silo_id: str,
        knowledge_version: int | None,
        top_k: int,
        filters: dict[str, Any] | None,
        include_superseded: bool,
        search_mode: str,
        results: list[dict[str, Any]],
    ) -> None:
        """Store results in the appropriate TTL bucket."""
        cache = self._pick_cache(layers)
        if cache is None:
            return

        key = self._build_key(
            effective_query,
            layers,
            silo_id,
            knowledge_version,
            top_k,
            filters,
            include_superseded,
            search_mode,
        )
        cache[key] = (results, time.time())

    def invalidate_silo(self, silo_id: str) -> None:
        """Evict all cache entries for a given silo.

        Scans all three caches and removes entries whose key contains silo_id
        at position 2 (index 2 in the key tuple).
        Collects keys first to avoid mutation-during-iteration.
        """
        for cache in (self._memory_cache, self._knowledge_cache, self._wisdom_cache):
            if cache is None:
                continue
            matching = [k for k in list(cache.keys()) if k[2] == silo_id]
            for k in matching:
                cache.pop(k, None)


async def get_knowledge_version(
    redis: RedisClient,
    silo_id: str,
) -> int | None:
    """Fetch the knowledge version counter for a silo from Redis.

    Returns None if Redis is unavailable or the key does not exist.
    """
    try:
        raw = await redis.get(f"silo:{silo_id}:knowledge_version")
        if raw is None:
            return None
        return int(raw)
    except Exception:
        logger.debug("get_knowledge_version_failed", silo_id=silo_id)
        return None
