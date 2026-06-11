"""Tests for ResultCacheStore integration in _context_query."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_result(
    node_id: str = "node-1",
    layer: str = "knowledge",
    content: str = "test content",
) -> MagicMock:
    r = MagicMock()
    r.node_id = node_id
    r.layer = layer
    r.content = content
    r.summary = None
    r.confidence = 0.9
    r.relevance_score = 0.8
    r.tags = []
    r.created_at = None
    return r


def _make_mock_settings(reranking_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.reranking.enabled = reranking_enabled
    s.reranking.expand_hard_queries = False
    s.causal.query_enabled = False
    s.epistemic_fusion.enabled = False
    cfg = MagicMock()
    cfg.enabled = True
    cfg.memory_ttl = 300
    cfg.knowledge_ttl = 3600
    cfg.wisdom_ttl = 1800
    cfg.maxsize = 1000
    s.result_cache = cfg
    return s


def _make_mock_silo_service() -> MagicMock:
    mock_silo = MagicMock()
    mock_silo.metadata = {}
    svc = MagicMock()
    svc.get_by_id = AsyncMock(return_value=mock_silo)
    return svc


_BASE_PATCHES = {
    "context_service.mcp.tools.context_query.get_mcp_auth_context": None,
    "context_service.mcp.tools.context_query.validate_silo_ownership": None,
    "context_service.mcp.tools.context_query.get_context_service": None,
    "context_service.mcp.tools.context_query.get_silo_service": None,
    "context_service.mcp.tools.context_query.get_settings": None,
    "context_service.mcp.tools.context_query.get_redis": None,
}


@pytest.mark.asyncio
async def test_context_query_result_cache_hit() -> None:
    """Pre-populate cache; second call should return cached results without querying."""
    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    # Reset module-level cache state so each test is independent
    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(return_value=[_make_mock_result()])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )
    # Pre-populate cache
    cached_results = [
        {
            "node_id": "node-cached",
            "layer": "knowledge",
            "content": "from cache",
            "summary": None,
            "confidence": 0.95,
            "relevance_score": 0.9,
            "tags": [],
            "created_at": None,
        }
    ]
    fresh_cache.set(
        "test query",
        None,
        "test-silo",
        0,
        10,
        None,
        False,
        "hybrid",
        cached_results,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo",
            query="test query",
            top_k=10,
        )

    assert result["cache_meta"]["result_cached"] is True
    assert result["cache_meta"]["cached_at"] is not None
    assert result["results"] == cached_results
    # Underlying store.query should not have been called
    mock_ctx_svc.query.assert_not_called()


@pytest.mark.asyncio
async def test_context_query_result_cache_miss_then_populate() -> None:
    """First call misses cache and populates it; second call hits the cache."""
    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(return_value=[_make_mock_result(node_id="live-node")])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        # First call: cache miss
        first = await _context_query(silo_id="test-silo", query="unique query miss", top_k=10)
        assert first["cache_meta"]["result_cached"] is False
        assert first["cache_meta"]["cached_at"] is None
        assert len(first["results"]) == 1
        assert first["results"][0]["node_id"] == "live-node"

        # Second call: cache hit
        second = await _context_query(silo_id="test-silo", query="unique query miss", top_k=10)
        assert second["cache_meta"]["result_cached"] is True
        assert second["results"][0]["node_id"] == "live-node"

    # store.query called exactly once (first call only)
    mock_ctx_svc.query.assert_called_once()


@pytest.mark.asyncio
async def test_context_query_bypass_cache() -> None:
    """With bypass_cache=True, cache is never consulted and results are not stored."""
    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(return_value=[_make_mock_result(node_id="bypass-node")])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )
    # Pre-populate with stale data
    stale_results = [
        {
            "node_id": "stale-node",
            "layer": "knowledge",
            "content": "stale",
            "summary": None,
            "confidence": 0.1,
            "relevance_score": 0.1,
            "tags": [],
            "created_at": None,
        }
    ]
    fresh_cache.set("bypass query", None, "test-silo", 0, 10, None, False, "hybrid", stale_results)

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo",
            query="bypass query",
            top_k=10,
            bypass_cache=True,
        )

    # Should have gone to the store despite cache being populated
    mock_ctx_svc.query.assert_called_once()
    assert result["results"][0]["node_id"] == "bypass-node"
    assert result["cache_meta"]["result_cached"] is False


@pytest.mark.asyncio
async def test_context_query_temporal_bypasses_cache() -> None:
    """Queries with as_of set skip cache entirely and do not include cache_meta."""
    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.temporal_query = AsyncMock(return_value=[{"node_id": "temporal-node"}])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo",
            query="temporal query",
            top_k=10,
            as_of="2025-01-01T00:00:00Z",
        )

    assert result["historical_query"] is True
    assert "cache_meta" not in result
    mock_ctx_svc.temporal_query.assert_called_once()


@pytest.mark.asyncio
async def test_context_query_intelligence_layer_not_cached() -> None:
    """Intelligence-layer queries always return result_cached=False (cache skips intelligence)."""
    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(
        return_value=[_make_mock_result(node_id="intel-node", layer="intelligence")]
    )

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=None),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        # First call
        first = await _context_query(
            silo_id="test-silo",
            query="intel query",
            layers=["intelligence"],
            top_k=10,
        )
        assert first["cache_meta"]["result_cached"] is False

        # Second call - should still miss because intelligence layer is never cached
        second = await _context_query(
            silo_id="test-silo",
            query="intel query",
            layers=["intelligence"],
            top_k=10,
        )
        assert second["cache_meta"]["result_cached"] is False

    # Both calls should have gone to the store
    assert mock_ctx_svc.query.call_count == 2


@pytest.mark.asyncio
async def test_context_query_max_age_seconds_evicts_stale() -> None:
    """Cache entry older than max_age_seconds is treated as a miss."""
    import time

    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(return_value=[_make_mock_result(node_id="fresh-node")])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )
    # Pre-populate the cache, then backdate the cached_at timestamp by 60 seconds
    stale_results = [
        {
            "node_id": "stale-node",
            "layer": "knowledge",
            "content": "stale content",
            "summary": None,
            "confidence": 0.5,
            "relevance_score": 0.5,
            "tags": [],
            "created_at": None,
        }
    ]
    fresh_cache.set(
        "max age stale query",
        None,
        "test-silo",
        0,
        10,
        None,
        False,
        "hybrid",
        stale_results,
    )
    # Backdate the cached_at by replacing the value in the underlying TTLCache
    assert fresh_cache._knowledge_cache is not None
    stale_key = next(iter(fresh_cache._knowledge_cache))
    fresh_cache._knowledge_cache[stale_key] = (stale_results, time.time() - 60)

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=0),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo",
            query="max age stale query",
            top_k=10,
            max_age_seconds=30,
        )

    # 60s > 30s limit: treated as cache miss, store.query must have been called
    mock_ctx_svc.query.assert_called_once()
    assert result["cache_meta"]["result_cached"] is False


@pytest.mark.asyncio
async def test_context_query_max_age_seconds_within_limit() -> None:
    """Cache entry younger than max_age_seconds is returned as a hit."""
    import time

    from context_service.cache.result_cache import ResultCacheStore
    from context_service.mcp.tools import context_query as cq_mod

    cq_mod._result_cache = None

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_ctx_svc = MagicMock()
    mock_ctx_svc.query = AsyncMock(return_value=[_make_mock_result(node_id="live-node")])

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    fresh_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )
    # Pre-populate the cache, then backdate by only 10 seconds
    recent_results = [
        {
            "node_id": "recent-node",
            "layer": "knowledge",
            "content": "recent content",
            "summary": None,
            "confidence": 0.9,
            "relevance_score": 0.85,
            "tags": [],
            "created_at": None,
        }
    ]
    fresh_cache.set(
        "max age recent query",
        None,
        "test-silo",
        0,
        10,
        None,
        False,
        "hybrid",
        recent_results,
    )
    # Backdate the cached_at by 10 seconds (within the 30s limit)
    assert fresh_cache._knowledge_cache is not None
    recent_key = next(iter(fresh_cache._knowledge_cache))
    fresh_cache._knowledge_cache[recent_key] = (recent_results, time.time() - 10)

    with (
        patch(
            "context_service.mcp.tools.context_query.get_mcp_auth_context",
            return_value=mock_auth,
        ),
        patch(
            "context_service.mcp.tools.context_query.validate_silo_ownership",
            return_value=None,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_context_service",
            return_value=mock_ctx_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_silo_service",
            return_value=mock_silo_svc,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_settings",
            return_value=mock_settings,
        ),
        patch("context_service.mcp.tools.context_query.get_redis", return_value=None),
        patch(
            "context_service.mcp.tools.context_query._get_result_cache",
            return_value=fresh_cache,
        ),
        patch(
            "context_service.mcp.tools.context_query.get_knowledge_version",
            new=AsyncMock(return_value=0),
        ),
    ):
        from context_service.mcp.tools.context_query import _context_query

        result = await _context_query(
            silo_id="test-silo",
            query="max age recent query",
            top_k=10,
            max_age_seconds=30,
        )

    # 10s < 30s limit: cache hit, store.query must NOT have been called
    mock_ctx_svc.query.assert_not_called()
    assert result["cache_meta"]["result_cached"] is True
    assert result["results"] == recent_results
