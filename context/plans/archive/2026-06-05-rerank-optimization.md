# Plan: Semantic Rerank Cache

**Goal:** Reduce rerank latency by caching results for similar queries  
**Approach:** Two-level cache (L1 exact match, L2 semantic similarity)  
**Effort:** ~2-3 hours  
**Status:** Ready

**Decision:** Keep current Vertex semantic-ranker (excellent quality), add caching to reduce redundant calls. Revisit reranker swap when volume justifies GPU cost.

## Phase 1: Semantic Rerank Cache (2-3 hours)

Cache rerank results by query similarity. If a new query is 95%+ similar to a cached query with the same documents, reuse cached scores.

### Task 1.1: Create SemanticRerankCache class (60 min)

New file: `src/context_service/cache/rerank_cache.py`

```python
class SemanticRerankCache:
    """Two-level cache for rerank results.
    
    L1: Exact match (TTLCache, in-process)
    L2: Semantic match (Qdrant collection, 0.95 cosine threshold)
    """
    
    def __init__(
        self,
        qdrant: AsyncQdrantClient,
        collection_name: str = "rerank_cache",
        similarity_threshold: float = 0.95,
        l1_ttl_seconds: int = 300,
        l1_maxsize: int = 1000,
    ): ...
    
    async def get(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        silo_id: str,
    ) -> list[tuple[str, float]] | None: ...
    
    async def set(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        scores: list[tuple[str, float]],
        silo_id: str,
    ) -> None: ...
```

Key implementation details:
- L1 key: `hash(query)[:16]:hash(sorted(doc_ids))[:16]`
- L2 filter: `silo_id == X AND doc_ids_hash == Y AND score >= 0.95`
- Store scores as `[(doc_id, score), ...]` for reconstruction

### Task 1.2: Add Qdrant collection setup (15 min)

File: `src/context_service/stores/qdrant.py`

Add method to ensure rerank_cache collection exists:
```python
async def ensure_rerank_cache_collection(self, vector_size: int = 768) -> None:
    """Create rerank_cache collection if not exists."""
```

Indexes needed:
- `silo_id` (keyword)
- `doc_ids_hash` (keyword)
- `created_at` (float, for eviction)

### Task 1.3: Wire cache into _apply_reranking (30 min)

File: `src/context_service/mcp/tools/context_query.py`

Update `_apply_reranking()` signature to accept query_embedding:
```python
async def _apply_reranking(
    query: str,
    query_embedding: list[float],  # NEW
    results: list[Any],
    settings: Any,
    silo_id: str,  # NEW
) -> tuple[list[Any], bool]:
```

Flow:
1. Check cache.get() first
2. On hit: reorder results by cached scores, return
3. On miss: call reranker, cache.set(), return

### Task 1.4: Add cache settings (10 min)

File: `src/context_service/config/settings.py`

```python
class RerankCacheSettings(BaseModel):
    enabled: bool = True
    similarity_threshold: float = 0.95
    l1_ttl_seconds: int = 300
    l1_maxsize: int = 1000
    l2_max_entries_per_silo: int = 1000
```

### Task 1.5: Add cache metrics (15 min)

File: `src/context_service/telemetry/metrics.py`

```python
def record_rerank_cache_hit(level: str, silo_id: str) -> None: ...
def record_rerank_cache_miss(silo_id: str) -> None: ...
```

### Task 1.6: Unit tests (30 min)

New file: `tests/cache/test_rerank_cache.py`

| Test | Validates |
|------|-----------|
| `test_l1_exact_hit` | Same query+docs returns cached scores |
| `test_l2_semantic_hit` | Similar query (>0.95) returns cached scores |
| `test_different_docs_miss` | Same query, different doc set = miss |
| `test_below_threshold_miss` | Similar query (<0.95) = miss |
| `test_cache_populates_l1_on_l2_hit` | L2 hit warms L1 |

### Task 1.7: Integration test (15 min)

File: `tests/integration/test_rerank_cache_flow.py`

End-to-end: recall with cache miss → cache set → similar query → cache hit

---

## Verification

```bash
just check                                    # lint + typecheck
just test -k rerank_cache                     # unit tests
just test tests/integration/test_rerank       # integration
```

Manual verification:
1. Deploy to dev
2. Run recall queries, check logs for cache hits/misses
3. Verify cache hits return in <20ms
4. Verify cache misses still work (Vertex ~600ms)

## Files Changed

| File | Change |
|------|--------|
| `src/context_service/cache/rerank_cache.py` | NEW |
| `src/context_service/stores/qdrant.py` | Add collection setup |
| `src/context_service/mcp/tools/context_query.py` | Wire cache into rerank flow |
| `src/context_service/config/settings.py` | Add cache settings |
| `src/context_service/telemetry/metrics.py` | Cache metrics |
| `tests/cache/test_rerank_cache.py` | NEW |
| `tests/integration/test_rerank_cache_flow.py` | NEW |

## Success Criteria

- [ ] `just check` passes
- [ ] All new tests pass
- [ ] Cache hit rate >40% on repeated query patterns
- [ ] Cache hit latency <20ms
- [ ] No regression on cache misses (Vertex still works)

## Rollback

Disable via `rerank_cache.enabled: false` in settings.

## Future

When volume justifies GPU cost (~50K+ queries/mo), consider:
- Jina v2 on Vertex endpoint (~$500/mo, ~50ms latency)
- Cohere via Model Garden or direct API
