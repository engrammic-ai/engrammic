# Phase 2: Tiered Result Cache

**Spec:** [2026-05-19-recall-optimization.md](../specs/2026-05-19-recall-optimization.md)
**Status:** planning
**Priority:** medium
**Depends on:** Phase 1 (embedding cache + TEI)

## Goal

Add per-layer in-process LRU caches with version-based invalidation to serve hot recall queries in <20ms without hitting Qdrant.

## Design Decisions

### Cross-layer composition strategy

Option A (per-layer parallel lookups, spec recommendation) vs Option B (cache the multi-layer result as a single entry keyed on sorted layer tuple).

**Decision: Option B for now.** The cache key includes the sorted layer tuple. Multi-layer results are cached as a single entry. Rationale: `ctx_svc.query` currently does one Qdrant call for all layers; splitting it N ways requires refactoring the query path. Option B gets most of the hit-rate benefit with minimal risk. Option A is the natural next step if per-layer invalidation granularity proves valuable.

Consequence: `[knowledge, wisdom]` and `[knowledge]` queries are separate cache entries. Correct - the result sets differ.

### What is cached (post-rerank, post-filter)

The cache stores `result_dicts` after `apply_threshold_filter` and reranking. On hit, reranking is skipped (~10ms saved). Access events are still emitted on cache hits (see Task 6) to keep heat/freshness signals accurate.

### Temporal queries bypass cache

Any call with `as_of` set routes through `ctx_svc.temporal_query` and must never touch the result cache. Enforced with an early return in `_context_query`.

### Full cache key

```
(query_hash, sorted_layers, silo_id, knowledge_version, top_k, filters_hash, include_superseded, search_mode)
```

- `query_hash`: sha256 of the **post-expansion** effective query, lowercased and stripped.
- `sorted_layers`: sorted layer strings joined by comma, or `"all"` when layers is None.
- `knowledge_version`: from Redis key `silo:{silo_id}:knowledge_version`. Omitted for memory-only queries.
- `filters_hash`: sha256 of JSON-serialized filters, or `"none"` when absent.

### cache_meta shape (merged with Phase 1)

```python
{
    "embedding_cached": bool | None,  # Phase 1 fills this; None until Phase 1 lands
    "result_cached": bool,
    "cached_at": str | None,          # ISO 8601 when result was cached
    "layer_ttls": dict[str, int],     # only layers actually queried
    "knowledge_version": int | None   # None for memory-only queries
}
```

### Single-flight / stampede

Deferred. Short TTLs and in-process LRU bound the stampede to one per pod per key. Revisit in Phase 4 if pod-level profiling shows it matters.

## Tasks

### Task 1: Add `ResultCacheConfig` to settings

**Files:**
- `src/context_service/config/settings.py`

**Changes:**
1. Add `ResultCacheConfig(BaseModel)` alongside `CacheConfig` (around line 516):

```python
class ResultCacheConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable in-process tiered result cache")
    memory_ttl: int = Field(default=300, description="Memory layer TTL in seconds (5 min)")
    knowledge_ttl: int = Field(default=3600, description="Knowledge layer TTL in seconds (1 hour)")
    wisdom_ttl: int = Field(default=1800, description="Wisdom layer TTL in seconds (30 min)")
    maxsize: int = Field(default=10000, description="Max entries per layer cache")
```

2. Add `result_cache: ResultCacheConfig = Field(default_factory=ResultCacheConfig)` to `Settings` alongside the existing `cache:` field.

**Test:** `test_settings_result_cache_defaults`

- [ ] Add config class and field
- [ ] Write test
- [ ] `uv run just check`

### Task 2: Implement `ResultCacheStore`

**Files:**
- `src/context_service/cache/result_cache.py` (new file)

**Changes:**
1. Create `ResultCacheStore` with one `TTLCache` per cacheable layer (memory, knowledge, wisdom). Intelligence excluded.
2. `_pick_cache(layers)` selects TTL bucket: intelligence in layers -> no cache; knowledge or None -> knowledge cache; wisdom only -> wisdom cache; memory only -> memory cache.
3. `get(effective_query, layers, silo_id, knowledge_version, top_k, filters, include_superseded, search_mode) -> tuple[results, cached_at] | None`
4. `set(...)` stores `(results, time.time())`.
5. `invalidate_silo(silo_id)` scans and evicts all keys containing `:{silo_id}:` - for tests and admin.
6. Standalone async helper `get_knowledge_version(redis, silo_id) -> int | None` in the same module.
7. **Required:** Add `cachetools` to `pyproject.toml` - it is not present.

**Test:** `test_result_cache_store_hit_miss` - set, get, verify; intelligence returns None; different silo does not collide.

**Test:** `test_result_cache_store_ttl_expiry` - `TTLCache(maxsize=10, ttl=1)`, write, sleep(2), assert miss.

**Test:** `test_get_knowledge_version_returns_none_on_redis_unavailable`

- [ ] Create `result_cache.py`
- [ ] Write tests
- [ ] `uv run just check`

### Task 3: Add `RedisClient.incr`

**Files:**
- `src/context_service/stores/redis.py`

**Changes:**
1. Add `async def incr(self, key: str) -> int` as a public method, delegating to `_incr_impl` guarded by `guard_degrade(STORE_REDIS, ..., 0)`.
2. `_incr_impl` calls `await self._redis.incr(key)` and returns the resulting integer.

**Test:** `test_redis_client_incr_returns_incremented_value` - mock `self._redis.incr` returning 5, assert `incr(key)` returns 5.

- [ ] Add `incr` method
- [ ] Write test
- [ ] `uv run just check`

### Task 4: Wire version bump on Knowledge writes

**Files:**
- `src/context_service/services/context.py`

**Changes:**
1. In `ContextService.store`, in the existing `_KNOWLEDGE_LAYER_TYPES` branch (line ~366), after the Custodian enqueue:

```python
# Note: self._cache is RedisClient, not ResultCacheStore
if self._cache is not None:
    asyncio.create_task(
        self._cache.incr(f"silo:{silo_id}:knowledge_version")
    )
```

Place this after the `create_task` call for Custodian enqueue (line ~370).

No other write paths need this - Claim and Fact are the only `_KNOWLEDGE_LAYER_TYPES`; Wisdom layer writes (Belief, ProposedBelief) invalidate via the wisdom TTL which is short enough.

**Test:** `test_knowledge_write_bumps_version` - mock `RedisClient.incr`, store a Fact node, assert `incr` called once with the correct key.

**Test:** `test_non_knowledge_write_does_not_bump_version` - store an Observation node, assert `incr` not called.

- [ ] Wire version bump
- [ ] Write tests
- [ ] `uv run just check`

### Task 5: Integrate cache into `_context_query`

**Files:**
- `src/context_service/mcp/tools/context_query.py`

**Changes:**
1. Import `ResultCacheStore`, `get_knowledge_version` from `context_service.cache.result_cache`. Add module-level `_get_result_cache() -> ResultCacheStore` lazy-init from settings (same pattern as other module-level helpers in this file).
2. Add `bypass_cache: bool = False` and `max_age_seconds: int | None = None` to `_context_query` signature.
3. After the `as_of` early-return block: if `as_of_dt is not None`, skip all cache logic (temporal queries bypass cache).
4. Fetch `knowledge_version = await get_knowledge_version(redis, silo_id)` before the expansion step. If Redis unavailable and returns `None`, treat as version `0` for cache key (effectively disables version-based invalidation but still caches).
5. After query expansion, check cache with `effective_query` (post-expansion) as the query hash input.
6. On hit: if `max_age_seconds` is set and entry is too old, treat as miss. Otherwise emit access events (via `_emit_access_events` helper from Task 6), assemble `cache_meta`, and return early.
7. On miss: run existing Qdrant + rerank + threshold-filter path; then call `_result_cache.set(...)` with `result_dicts`; assemble `cache_meta`.
8. Add helper `_layer_ttls_for(layers: list[str] | None) -> dict[str, int]` reading from `get_settings().result_cache`.
9. Include `cache_meta` in all returned dicts.

**Test:** `test_context_query_result_cache_hit`
**Test:** `test_context_query_result_cache_miss_then_populate`
**Test:** `test_context_query_bypass_cache`
**Test:** `test_context_query_max_age_seconds_evicts_stale`
**Test:** `test_context_query_temporal_bypasses_cache`
**Test:** `test_context_query_intelligence_layer_not_cached`

- [ ] Integrate cache logic
- [ ] Write tests
- [ ] `uv run just check`

### Task 6: Extract `_emit_access_events` helper and replay on hits

**Files:**
- `src/context_service/mcp/tools/context_query.py`

**Changes:**
1. Extract the existing `asyncio.gather` + `asyncio.wait_for` block for `emit_access_event` into `async def _emit_access_events(redis, silo_id, results)`.
2. Replace the inline block on the miss path with a call to this helper.
3. Call the same helper in the cache-hit branch (Task 5).

**Test:** `test_access_events_emitted_on_cache_hit` - cache a result, call `_context_query`, assert `emit_access_event` was called for each node_id.

- [ ] Extract helper
- [ ] Wire into both paths
- [ ] Write test
- [ ] `uv run just check`

### Task 7: Thread parameters through `context_recall` and `recall`

**Files:**
- `src/context_service/mcp/tools/context_recall.py`
- `src/context_service/mcp/tools/recall.py`

**Changes:**
1. Add `bypass_cache: bool = False` and `max_age_seconds: int | None = None` to `_context_recall` signature.
2. Forward them to `_context_query` in the `query and depth == 0` branch only. Graph and get-by-id branches are unaffected.
3. Add both parameters to the registered `context_recall` MCP tool function and thread through to `_context_recall`.
4. **Important:** Also update `recall.py` which wraps `context_recall` - add both parameters to `_recall_impl` and the registered `recall` MCP tool function, threading through to `_context_recall`. This is the public MCP surface agents use.

**Test:** `test_context_recall_threads_bypass_cache` - mock `_context_query`, call `_context_recall(bypass_cache=True)`, assert mock received `bypass_cache=True`.

**Test:** `test_recall_threads_bypass_cache` - mock `_context_recall`, call `recall(bypass_cache=True)`, assert mock received `bypass_cache=True`.

**Test:** `test_context_query_none_knowledge_version` - when `get_knowledge_version` returns `None`, cache key uses `0` as version.

- [ ] Thread parameters
- [ ] Write test
- [ ] `uv run just check`

### Task 8: Integration test - invalidation on Knowledge write

**Files:**
- `tests/test_result_cache_invalidation.py` (new file)

**Changes:**
1. Populate result cache for a knowledge query on silo S (version=0).
2. Simulate a Knowledge write: call `ContextService.store` with `node_type="Fact"`, assert `incr` mock called, version is now 1.
3. Call `_context_query` again with identical inputs.
4. Assert `cache_meta["result_cached"]` is `False` (version mismatch evicts old entry).
5. Assert result list is non-empty (Qdrant mock returns results).

**Test:** `test_knowledge_write_invalidates_result_cache`

- [ ] Write integration test
- [ ] `uv run just check`

## Completion Checklist

- [ ] `ResultCacheConfig` in settings, all defaults match spec TTLs
- [ ] `ResultCacheStore` implemented and unit-tested
- [ ] `RedisClient.incr` added and tested
- [ ] Knowledge writes bump `silo:{silo_id}:knowledge_version`
- [ ] `_context_query` checks cache, populates on miss, skips on `as_of` or intelligence layer
- [ ] `bypass_cache` and `max_age_seconds` exposed on `context_recall` tool
- [ ] Access events emitted on cache hits via extracted helper
- [ ] `cache_meta` present in all query responses, Phase 1 key reserved
- [ ] Integration invalidation test passes
- [ ] `just check` passes (mypy strict + ruff)

## Rollout

1. Merge with `enabled: true` default - cache is transparent
2. Monitor `cache_meta.result_cached` in responses via logging/OTEL
3. If hit rate is low, investigate query variation patterns
4. If staleness complaints arise, tune TTLs or add `bypass_cache` to problematic flows

## Success Criteria

- Hot recall queries (cache hit): <20ms
- Result cache hit rate: >30% for Knowledge layer after warm-up
- No regression on Somnus accuracy benchmarks
- `just check` passes
