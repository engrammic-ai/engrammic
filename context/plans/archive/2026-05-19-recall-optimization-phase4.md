# Phase 4: Similarity Cache

**Spec:** [2026-05-19-recall-optimization.md](../specs/2026-05-19-recall-optimization.md)
**Status:** planning
**Priority:** low (optional optimization)
**Depends on:** Phase 1 (embedding cache)

## Goal

Extend the Phase 1 exact-match embedding cache to reuse cached embeddings for semantically near-identical queries by maintaining a bounded index of recent query vectors in Redis and checking cosine similarity on exact-match miss.

## Design Notes

### Data structure choice

Redis is vanilla (no RedisSearch/HNSW modules assumed). Two viable options:

**Option A (chosen): Redis list + Python NumPy linear scan**
Store up to N recent embeddings as a Redis list. On miss, fetch all N, compute cosine similarity in NumPy (vectorized dot products), return best match above threshold. At N=500 and 512 dims: ~250KB transferred per miss, NumPy dot on a (500, 512) float32 matrix takes ~0.1ms. Redis round-trip dominates, total overhead ~2-5ms.

**Option B: Qdrant dedicated collection**
Accurate sub-linear search, but adds operational complexity and crosses the "no extra infra" line for an optional optimization. Deferred.

### Redis key layout

```
cache:simidx:{provider}:embeddings   # Redis list of encoded (hash, vector) entries
```

**Provider-namespaced** (not global): Different silos may use different embedding providers (jina, vertex, litellm). Mixing vectors from different providers would return incorrect similarity matches. The provider key comes from embeddings config.

Example keys:
- `cache:simidx:tei:embeddings`
- `cache:simidx:vertex:embeddings`

### Memory bounds

- 512 dims x float16 = 1KB per embedding
- Default cap: 500 entries = ~500KB in Redis
- Configurable up to 5000 entries = ~5MB

### Threshold rationale

At cosine similarity > 0.95, two queries are semantically near-identical (e.g. "What is X?" vs "What's X?"). Antonyms score ~0.7-0.8; paraphrases score 0.97+. False positives at 0.95 are negligible - worst case is returning an embedding computed for a slightly different phrasing, which produces nearly identical Qdrant results. Tunable via `SimilarityCacheConfig.threshold`.

### Immediate vs. forward reuse

The similarity index provides forward-looking reuse: a near-identical query hits on its second occurrence. The first occurrence is always a cold miss (we cannot do cosine similarity without the query vector, which is what we're trying to avoid computing). The `similarity_lookup_with_vector()` method is provided for retroactive hit detection and metrics.

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/cache/similarity_cache.py` | New: `SimilarityEmbeddingCache` |
| `src/context_service/cache/__init__.py` | Export `SimilarityEmbeddingCache` |
| `src/context_service/config/settings.py` | Add `SimilarityCacheConfig` |
| `tests/cache/test_similarity_cache.py` | Unit tests (fake Redis, no network) |

## Tasks

### Task 1: Add SimilarityCacheConfig to Settings

**Files:**
- `src/context_service/config/settings.py`

**Changes:**

Add `SimilarityCacheConfig` model after `CacheConfig`:

```python
class SimilarityCacheConfig(BaseModel):
    """Configuration for Phase 4 similarity embedding cache."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(
        default=False,
        description="Enable similarity-based embedding reuse on exact-match miss.",
    )
    threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum cosine similarity to reuse a cached embedding.",
    )
    max_entries: int = Field(
        default=500,
        ge=10,
        le=5000,
        description="Maximum number of recent query embeddings kept in the similarity index.",
    )
    index_ttl: int = Field(
        default=86400,
        ge=60,
        description="TTL in seconds applied to the similarity index key on each write.",
    )
```

Add field to `Settings`:

```python
similarity_cache: SimilarityCacheConfig = Field(default_factory=SimilarityCacheConfig)
```

- [ ] Add `SimilarityCacheConfig` class
- [ ] Add `similarity_cache` field to `Settings`
- [ ] `uv run just check`

### Task 2: Implement SimilarityEmbeddingCache

**Files:**
- `src/context_service/cache/similarity_cache.py` (new)

**Changes:**

Create `SimilarityEmbeddingCache` class with:

- `__init__(redis, exact_cache)` - wraps existing `EmbeddingCache`
- `get(text, task)` - delegates to exact cache (no similarity lookup without vector)
- `set(text, task, vector)` - caches in exact cache + pushes to similarity index. **Note:** Input `vector` is `list[float]`, convert to float16 for index storage, keep float32/list[float] for exact cache to maintain codec boundary clarity.
- `similarity_lookup_with_vector(query_vector, text_hash)` - checks index for cosine > threshold
- `_index_push(text_hash, vector)` - `lpush + ltrim + expire` pipeline

Key implementation details:
- Store float16 for 2x memory reduction (convert from float32 input)
- L2 normalize vectors before cosine comparison
- Vectorized NumPy dot product for efficiency
- **Verify numpy is in pyproject.toml** before implementing - required for vectorized ops

- [ ] Create `similarity_cache.py`
- [ ] `uv run just check`

### Task 3: Wire into Cache Module

**Files:**
- `src/context_service/cache/__init__.py`

**Changes:**

```python
from context_service.cache.similarity_cache import SimilarityEmbeddingCache

__all__ = ["AliasCache", "EmbeddingCache", "LookupCache", "NodeCache", "SimilarityEmbeddingCache"]
```

- [ ] Update `__init__.py`
- [ ] `uv run just check`

### Task 4: Unit Tests

**Files:**
- `tests/cache/test_similarity_cache.py` (new)

Tests use a fake in-memory Redis (no network). Key cases:

| Test | Validates |
|------|-----------|
| `test_encode_decode_roundtrip` | float16 codec preserves vector within tolerance |
| `test_l2_normalize_*` | normalization edge cases (unit, zero) |
| `test_set_pushes_to_index` | `set()` populates index when enabled |
| `test_disabled_skips_index` | `set()` does not touch index when `enabled=False` |
| `test_index_trims_to_max_entries` | `lpush+ltrim` holds at `max_entries` |
| `test_similarity_lookup_above_threshold` | near-identical vector returns match |
| `test_similarity_lookup_below_threshold` | orthogonal vector returns None |
| `test_similarity_lookup_empty_index` | returns None gracefully on empty index |
| `test_get_exact_match_wins` | `get()` returns exact cached embedding |
| `test_get_returns_none_on_miss` | `get()` returns None when nothing cached |
| `test_set_converts_float32_to_float16` | input list[float] stored as float16 in index |
| `test_different_providers_use_different_indexes` | provider namespace prevents cross-contamination |

- [ ] Create test file with all cases
- [ ] `uv run pytest tests/cache/test_similarity_cache.py -v`
- [ ] `uv run pytest tests/cache/ -v` - no regressions

### Task 5: Final Verification and Commit

- [ ] `uv run just check` - mypy strict + ruff
- [ ] `uv run pytest tests/cache/ -v` - all pass
- [ ] Commit

## Done Criteria

- [ ] `SimilarityCacheConfig` in `Settings`, default `enabled=False`
- [ ] `SimilarityEmbeddingCache` with exact-match delegation, bounded index push, `similarity_lookup_with_vector()` for retroactive hit detection
- [ ] Redis index bounded to `max_entries` via `lpush + ltrim` pipeline
- [ ] All unit tests pass (codec, threshold boundary, trim, empty index, enabled/disabled)
- [ ] `just check` passes
- [ ] Feature is off by default; no behavior change to existing code paths

## Out of Scope / Deferred

- Immediate reuse on first miss (requires fingerprint embedding or two-step embedding path)
- Per-task or per-silo indexes (global is correct: embeddings are pure text functions)
- RedisSearch/HNSW index (revisit only if max_entries needs to grow past 5000)
- OTEL counter for retroactive hit rate (follow-up once integration is wired into recall path)

## Success Criteria

- Feature ships disabled by default
- When enabled, reduces embedding compute for semantically similar queries
- No regression when disabled
- `just check` passes
