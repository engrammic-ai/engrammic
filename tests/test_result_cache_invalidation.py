"""Integration test: Knowledge write invalidates result cache via version bump.

Flow:
1. Populate result cache for a knowledge query on silo S (version=0).
2. Verify the first query returns a cache hit.
3. Simulate a Knowledge write: call ContextService.store with node_type="Fact".
   - ContextService.store calls redis.incr("silo:{silo_id}:knowledge_version").
4. Mock get_knowledge_version to return 1 on the next call (version bumped).
5. Call _context_query again with identical inputs.
6. Assert cache_meta["result_cached"] is False (version mismatch -> cache miss).
7. Assert ctx_svc.query was called (not a cache hit).
"""

from __future__ import annotations

import contextlib
import inspect
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.cache.result_cache import ResultCacheStore
from context_service.services.context import ContextService
from context_service.services.models import ScopeContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SILO_UUID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
SILO_STR = str(SILO_UUID)


def _make_mock_result(node_id: str = "node-1", layer: str = "knowledge") -> MagicMock:
    r = MagicMock()
    r.node_id = node_id
    r.layer = layer
    r.content = "some knowledge content"
    r.summary = None
    r.confidence = 0.9
    r.relevance_score = 0.85
    r.tags = []
    r.created_at = None
    return r


def _make_mock_settings(reranking_enabled: bool = False) -> MagicMock:
    s = MagicMock()
    s.reranking.enabled = reranking_enabled
    s.reranking.expand_hard_queries = False
    s.causal.query_enabled = False
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


def _make_context_service() -> tuple[ContextService, AsyncMock]:
    """Build a ContextService with mocked dependencies and return (svc, redis_mock)."""
    memgraph = AsyncMock()
    memgraph.execute_write = AsyncMock(return_value=[])
    memgraph.execute_query = AsyncMock(return_value=[])

    qdrant = AsyncMock()
    qdrant.upsert = AsyncMock(return_value=None)

    embedding = AsyncMock()
    embedding.embed_single = AsyncMock(return_value=[0.1, 0.2, 0.3])

    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock(return_value=None)
    redis_mock.set_nx = AsyncMock(return_value=True)
    redis_mock.incr = AsyncMock(return_value=1)

    svc = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        cache=redis_mock,
    )
    return svc, redis_mock


_STORE_SETTINGS_PATCH = {
    "expansion_generation_enabled": False,
    "heat_ranking_enabled": False,
    "heat_weight": 0.0,
    "freshness_weight": 0.0,
    "freshness_sigma_days": 30,
}

# Cache-keyed result we'll pre-populate at version=0
_CACHED_RESULTS = [
    {
        "node_id": "cached-node-1",
        "layer": "knowledge",
        "content": "Cached knowledge entry",
        "summary": None,
        "confidence": 0.9,
        "relevance_score": 0.85,
        "tags": [],
        "created_at": None,
    }
]

# Result the store returns on a fresh (live) query
_LIVE_RESULTS = [
    {
        "node_id": "live-node-1",
        "layer": "knowledge",
        "content": "Freshly queried result",
        "summary": None,
        "confidence": 0.95,
        "relevance_score": 0.9,
        "tags": [],
        "created_at": None,
    }
]

_QUERY = "what do we know about protein folding"


@pytest.mark.asyncio
async def test_knowledge_write_invalidates_result_cache() -> None:
    """End-to-end: cache hit at version=0 becomes a miss after Knowledge write bumps to 1."""
    from context_service.mcp.tools import context_query as cq_mod

    # Reset module-level cache so this test is isolated.
    cq_mod._result_cache = None

    # --- Build shared objects -------------------------------------------------
    result_cache = ResultCacheStore(
        memory_ttl=300,
        knowledge_ttl=3600,
        wisdom_ttl=1800,
        maxsize=100,
        enabled=True,
    )

    # Pre-populate cache at knowledge_version=0
    result_cache.set(
        effective_query=_QUERY,
        layers=["knowledge"],
        silo_id=SILO_STR,
        knowledge_version=0,
        top_k=10,
        filters=None,
        include_superseded=False,
        search_mode="hybrid",
        results=_CACHED_RESULTS,
    )

    ctx_svc, redis_mock = _make_context_service()

    # ctx_svc.query returns a live result when the cache misses
    live_mock_result = _make_mock_result(node_id="live-node-1")
    ctx_svc_query_mock = AsyncMock(return_value=[live_mock_result])
    ctx_svc.query = ctx_svc_query_mock  # type: ignore[method-assign]

    mock_auth = MagicMock()
    mock_auth.org_id = "test-org"

    mock_settings = _make_mock_settings()
    mock_silo_svc = _make_mock_silo_service()

    # Provide a non-None redis sentinel so that _context_query calls get_knowledge_version.
    # get_knowledge_version itself is patched separately per call to control the version.
    mock_redis = MagicMock()

    # Factory to build a fresh set of base patches each time (patch objects cannot be reused)
    def _make_base_patches() -> list[Any]:
        return [
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
                return_value=ctx_svc,
            ),
            patch(
                "context_service.mcp.tools.context_query.get_silo_service",
                return_value=mock_silo_svc,
            ),
            patch(
                "context_service.mcp.tools.context_query.get_settings",
                return_value=mock_settings,
            ),
            # Non-None redis so the code path reaches get_knowledge_version
            patch(
                "context_service.mcp.tools.context_query.get_redis",
                return_value=mock_redis,
            ),
            patch(
                "context_service.mcp.tools.context_query._get_result_cache",
                return_value=result_cache,
            ),
        ]

    # --- Step 1: First query should hit the pre-populated cache (version=0) ---
    from context_service.mcp.tools.context_query import _context_query

    with contextlib.ExitStack() as stack:
        for p in _make_base_patches():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "context_service.mcp.tools.context_query.get_knowledge_version",
                new=AsyncMock(return_value=0),
            )
        )
        first_result = await _context_query(
            silo_id=SILO_STR,
            query=_QUERY,
            layers=["knowledge"],
            top_k=10,
        )

    assert first_result["cache_meta"]["result_cached"] is True, (
        "Expected a cache hit on first call with version=0"
    )
    assert first_result["cache_meta"]["knowledge_version"] == 0
    ctx_svc_query_mock.assert_not_called()

    # --- Step 2: Simulate a Knowledge write (Fact node) -----------------------
    store_settings_mock = MagicMock(**_STORE_SETTINGS_PATCH)
    store_settings_mock.identities.custodian.enabled = False

    created_coros: list[object] = []

    with (
        patch(
            "context_service.services.context.get_settings",
            return_value=store_settings_mock,
        ),
        patch(
            "context_service.services.context.asyncio.create_task",
            side_effect=lambda coro: created_coros.append(coro),
        ),
    ):
        scope = ScopeContext(org_id="test-org", silo_id=SILO_UUID)
        await ctx_svc.store(
            scope=scope,
            content="Protein folding is driven by hydrophobic collapse",
            node_type="Fact",
            properties={"confidence": 0.92},
        )

    # Drain all captured coroutines so that incr is actually invoked.
    for coro in created_coros:
        if inspect.isawaitable(coro):
            await coro  # type: ignore[misc]

    # Verify incr was called with the correct key
    expected_incr_key = f"silo:{SILO_UUID}:knowledge_version"
    redis_mock.incr.assert_called_once_with(expected_incr_key)

    # --- Step 3: Second query — version=1 causes a cache miss -----------------
    with contextlib.ExitStack() as stack:
        for p in _make_base_patches():
            stack.enter_context(p)
        stack.enter_context(
            patch(
                "context_service.mcp.tools.context_query.get_knowledge_version",
                new=AsyncMock(return_value=1),
            )
        )
        second_result = await _context_query(
            silo_id=SILO_STR,
            query=_QUERY,
            layers=["knowledge"],
            top_k=10,
        )

    # Cache miss: version mismatch (0 vs 1) means the old entry is not found
    assert second_result["cache_meta"]["result_cached"] is False, (
        "Expected a cache miss after knowledge version bump from 0 to 1"
    )
    assert second_result["cache_meta"]["knowledge_version"] == 1

    # The store must have been queried (not a cache hit)
    ctx_svc_query_mock.assert_called_once()

    # Results come from the live store path
    assert len(second_result["results"]) >= 1
    assert second_result["results"][0]["node_id"] == "live-node-1"
