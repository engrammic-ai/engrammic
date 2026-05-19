"""Tests for ResultCacheStore and get_knowledge_version."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest
from cachetools import TTLCache

from context_service.cache.result_cache import ResultCacheStore, get_knowledge_version


def _make_store(**kwargs: Any) -> ResultCacheStore:
    """Create a ResultCacheStore with small defaults for testing."""
    defaults: dict[str, Any] = {
        "memory_ttl": 60,
        "knowledge_ttl": 120,
        "wisdom_ttl": 90,
        "maxsize": 100,
    }
    defaults.update(kwargs)
    return ResultCacheStore(**defaults)


SAMPLE_RESULTS: list[dict[str, Any]] = [
    {"node_id": "n1", "content": "hello"},
    {"node_id": "n2", "content": "world"},
]


class TestResultCacheStoreHitMiss:
    def test_miss_returns_none_before_set(self) -> None:
        store = _make_store()
        result = store.get(
            effective_query="test query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert result is None

    def test_set_then_get_returns_results(self) -> None:
        store = _make_store()
        store.set(
            effective_query="test query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        hit = store.get(
            effective_query="test query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert hit is not None
        results, cached_at = hit
        assert results == SAMPLE_RESULTS
        assert cached_at <= time.time()

    def test_intelligence_layer_returns_none_on_get(self) -> None:
        store = _make_store()
        result = store.get(
            effective_query="test query",
            layers=["intelligence"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert result is None

    def test_intelligence_layer_set_is_noop(self) -> None:
        store = _make_store()
        # Should not raise and should not cache
        store.set(
            effective_query="test query",
            layers=["intelligence"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        result = store.get(
            effective_query="test query",
            layers=["intelligence"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert result is None

    def test_memory_layer_cached(self) -> None:
        store = _make_store()
        store.set(
            effective_query="mem query",
            layers=["memory"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=5,
            filters=None,
            include_superseded=False,
            search_mode="semantic",
            results=SAMPLE_RESULTS,
        )
        hit = store.get(
            effective_query="mem query",
            layers=["memory"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=5,
            filters=None,
            include_superseded=False,
            search_mode="semantic",
        )
        assert hit is not None

    def test_wisdom_layer_cached(self) -> None:
        store = _make_store()
        store.set(
            effective_query="wisdom query",
            layers=["wisdom"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=5,
            filters=None,
            include_superseded=False,
            search_mode="semantic",
            results=SAMPLE_RESULTS,
        )
        hit = store.get(
            effective_query="wisdom query",
            layers=["wisdom"],
            silo_id="silo-1",
            knowledge_version=None,
            top_k=5,
            filters=None,
            include_superseded=False,
            search_mode="semantic",
        )
        assert hit is not None

    def test_none_layers_uses_knowledge_cache(self) -> None:
        store = _make_store()
        store.set(
            effective_query="all layers query",
            layers=None,
            silo_id="silo-1",
            knowledge_version=5,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        hit = store.get(
            effective_query="all layers query",
            layers=None,
            silo_id="silo-1",
            knowledge_version=5,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert hit is not None

    def test_key_collision_on_different_params(self) -> None:
        store = _make_store()
        store.set(
            effective_query="query A",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        # Different top_k -> different cache key -> miss
        miss = store.get(
            effective_query="query A",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=20,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert miss is None

    def test_knowledge_version_mismatch_is_miss(self) -> None:
        store = _make_store()
        store.set(
            effective_query="versioned query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        miss = store.get(
            effective_query="versioned query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=2,  # version bumped
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert miss is None


class TestResultCacheStoreDifferentSiloNoCollision:
    def test_different_silos_do_not_share_cache(self) -> None:
        store = _make_store()
        store.set(
            effective_query="shared query",
            layers=["knowledge"],
            silo_id="silo-A",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        miss = store.get(
            effective_query="shared query",
            layers=["knowledge"],
            silo_id="silo-B",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert miss is None

    def test_invalidate_silo_evicts_only_target(self) -> None:
        store = _make_store()
        # Populate two silos
        for silo in ("silo-A", "silo-B"):
            store.set(
                effective_query="query",
                layers=["knowledge"],
                silo_id=silo,
                knowledge_version=1,
                top_k=10,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
                results=SAMPLE_RESULTS,
            )

        store.invalidate_silo("silo-A")

        assert (
            store.get(
                effective_query="query",
                layers=["knowledge"],
                silo_id="silo-A",
                knowledge_version=1,
                top_k=10,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
            )
            is None
        )
        assert (
            store.get(
                effective_query="query",
                layers=["knowledge"],
                silo_id="silo-B",
                knowledge_version=1,
                top_k=10,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
            )
            is not None
        )


class TestResultCacheStoreTtlExpiry:
    def test_ttl_expiry_returns_miss(self) -> None:
        """Entry expires after TTL seconds (tested with short TTL + sleep)."""
        # Use a raw TTLCache with ttl=1 to avoid sleeping in production-sized caches
        short_cache: TTLCache[tuple[Any, ...], str] = TTLCache(maxsize=10, ttl=1)
        key = ("test-key",)
        short_cache[key] = "value"

        assert short_cache.get(key) == "value"

        time.sleep(1.1)

        assert short_cache.get(key) is None

    def test_result_cache_store_entry_expires(self) -> None:
        """ResultCacheStore with ttl=1 expires entries after 1 second."""
        store = ResultCacheStore(
            memory_ttl=1,
            knowledge_ttl=1,
            wisdom_ttl=1,
            maxsize=10,
        )
        store.set(
            effective_query="expiry test",
            layers=["knowledge"],
            silo_id="silo-exp",
            knowledge_version=0,
            top_k=5,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        assert (
            store.get(
                effective_query="expiry test",
                layers=["knowledge"],
                silo_id="silo-exp",
                knowledge_version=0,
                top_k=5,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
            )
            is not None
        )

        time.sleep(1.1)

        assert (
            store.get(
                effective_query="expiry test",
                layers=["knowledge"],
                silo_id="silo-exp",
                knowledge_version=0,
                top_k=5,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
            )
            is None
        )


class TestResultCacheStoreDisabled:
    """Verify that setting enabled=False makes the cache a no-op."""

    def test_get_returns_none_when_disabled(self) -> None:
        store = ResultCacheStore(
            memory_ttl=60,
            knowledge_ttl=120,
            wisdom_ttl=90,
            maxsize=100,
            enabled=False,
        )
        store.set(
            effective_query="some query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
            results=SAMPLE_RESULTS,
        )
        result = store.get(
            effective_query="some query",
            layers=["knowledge"],
            silo_id="silo-1",
            knowledge_version=1,
            top_k=10,
            filters=None,
            include_superseded=False,
            search_mode="hybrid",
        )
        assert result is None

    def test_invalidate_silo_noop_when_disabled(self) -> None:
        store = ResultCacheStore(
            memory_ttl=60,
            knowledge_ttl=120,
            wisdom_ttl=90,
            maxsize=100,
            enabled=False,
        )
        # Should not raise when cache buckets are None
        store.invalidate_silo("silo-1")

    def test_all_layers_return_none_when_disabled(self) -> None:
        store = ResultCacheStore(
            memory_ttl=60,
            knowledge_ttl=120,
            wisdom_ttl=90,
            maxsize=100,
            enabled=False,
        )
        for layer in (["memory"], ["knowledge"], ["wisdom"], None):
            store.set(
                effective_query="q",
                layers=layer,
                silo_id="silo-1",
                knowledge_version=1,
                top_k=5,
                filters=None,
                include_superseded=False,
                search_mode="hybrid",
                results=SAMPLE_RESULTS,
            )
            assert (
                store.get(
                    effective_query="q",
                    layers=layer,
                    silo_id="silo-1",
                    knowledge_version=1,
                    top_k=5,
                    filters=None,
                    include_superseded=False,
                    search_mode="hybrid",
                )
                is None
            )


class TestGetKnowledgeVersion:
    @pytest.mark.asyncio
    async def test_returns_version_when_redis_has_value(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=b"42")

        version = await get_knowledge_version(mock_redis, "silo-1")

        assert version == 42
        mock_redis.get.assert_called_once_with("silo:silo-1:knowledge_version")

    @pytest.mark.asyncio
    async def test_returns_none_when_key_missing(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        version = await get_knowledge_version(mock_redis, "silo-1")

        assert version is None

    @pytest.mark.asyncio
    async def test_returns_none_on_redis_unavailable(self) -> None:
        """Returns None when Redis raises (e.g. connection error)."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))

        version = await get_knowledge_version(mock_redis, "silo-1")

        assert version is None

    @pytest.mark.asyncio
    async def test_returns_none_on_generic_exception(self) -> None:
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=Exception("unexpected"))

        version = await get_knowledge_version(mock_redis, "silo-1")

        assert version is None
