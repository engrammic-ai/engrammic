# Recall Optimization Spec

Status: Draft
Date: 2026-05-19
Inspired by: DeepSeek V4 Engram research, embedding literature review

## Problem

Current recall flow has several inefficiencies:

| Stage | Current Latency | Target | Issue |
|-------|-----------------|--------|-------|
| Embedding | ~500ms | <50ms | Raw transformers inference, no caching |
| Qdrant search | ~100ms | ~50ms | Full 768-dim vectors, no quantization |
| Reranking | ~100ms | ~50ms | Already optimized |
| **Total** | **~700ms** | **<250ms** | 3x over target |

The 500ms embedding bottleneck is the primary issue. Secondary: repeated queries re-compute embeddings, no layer-aware caching.

## Decision Log

### Options Considered

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A: Exact-match query cache** | Hash query text, cache results | Simple, O(1) lookup | Low hit rate for varied NL queries |
| **B: Embedding cache only** | Cache query embeddings in Redis | High hit rate, 500ms saved | Still runs Qdrant on every query |
| **C: Similarity cache** | Cosine match against cached embeddings | Near-match hits, skip embed | Adds comparison overhead |
| **D: Tiered result cache** | Layer-dependent TTLs, version invalidation | Respects EAG semantics | More complex invalidation |
| **E: Full stack (chosen)** | TEI + Matryoshka + similarity cache + tiered results | Best latency, respects semantics | Implementation effort |

### Decision

**Option E: Full stack optimization**

Rationale:
- TEI/FastEmbed addresses the 500ms bottleneck directly (10x improvement)
- Matryoshka 512-dim reduces storage and search time with negligible quality loss
- Similarity cache handles semantic near-matches (not just exact)
- Tiered result cache respects layer semantics (Memory ephemeral, Knowledge stable)
- Combined: <100ms hot path, <200ms cold path

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      recall(query, layers)                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  1. SIMILARITY CACHE (Redis)                                 │
│     ─────────────────────────────────────────────────────── │
│     Key: emb:{sha256(normalized_query)}                      │
│     Value: embedding vector (512-dim, float16)               │
│     TTL: 7 days                                              │
│                                                              │
│     On lookup:                                               │
│     - Exact hash match → return cached embedding             │
│     - No match → compute embedding, cache it                 │
│                                                              │
│     Optional (phase 2): similarity search against recent     │
│     query embeddings, cosine > 0.95 → reuse embedding        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  2. EMBEDDING (TEI/FastEmbed)                                │
│     ─────────────────────────────────────────────────────── │
│     Model: nomic-ai/nomic-embed-text-v1.5                    │
│     Dimensions: 512 (Matryoshka truncation)                  │
│     Backend: HuggingFace TEI or Qdrant FastEmbed             │
│     Target latency: <50ms                                    │
│                                                              │
│     Note: Existing Vertex text-embedding-005 remains for     │
│     document ingestion (768-dim). Query-time uses 512-dim    │
│     with Matryoshka compatibility.                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  3. RESULT CACHE (in-process LRU)                            │
│     ─────────────────────────────────────────────────────── │
│     Key: (query_hash, layer, silo_id, knowledge_version)     │
│     Value: list[node_id, score]                              │
│                                                              │
│     Layer-dependent TTL:                                     │
│     - memory: 5 min (ephemeral observations)                 │
│     - knowledge: 1 hour (stable facts)                       │
│     - wisdom: 30 min (derived from knowledge)                │
│     - intelligence: no cache (session-specific)              │
│                                                              │
│     Cross-layer queries: compose from single-layer caches,   │
│     merge and rerank (rerank is cheap ~10ms)                 │
└─────────────────────────────────────────────────────────────┘
                              │ miss
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  4. QDRANT SEARCH                                            │
│     ─────────────────────────────────────────────────────── │
│     Mode: hybrid (dense + sparse, RRF k=60)                  │
│     Quantization: scalar (int8), 4x storage reduction        │
│     Vectors: 512-dim (Matryoshka)                            │
│                                                              │
│     Future: add sparse vectors for BM25-style retrieval      │
│     (better for exact entity names, technical identifiers)   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  5. RERANK + FILTER (existing)                               │
│     ─────────────────────────────────────────────────────── │
│     Vertex semantic-ranker-default@latest                    │
│     Threshold filtering per layer                            │
│     Quality scoring                                          │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Similarity Cache

**Scope**: Global (not per-silo). Embeddings are pure functions of text.

**Security**: Query text hashed in key, no leakage risk:
```python
key = f"emb:{sha256(query.lower().strip())}"
```

**Storage format**: 
- 512 floats × 2 bytes (float16) = 1KB per embedding
- 100K queries = 100MB in Redis (trivial)

**Phase 2 enhancement**: Instead of exact-match only, maintain a small index of recent query embeddings. On miss, check cosine similarity against last N queries. If > 0.95, reuse that embedding. Amortizes embedding cost across semantically similar queries.

### 2. TEI/FastEmbed Backend

**Why switch from Vertex**:
- Vertex text-embedding-005: ~500ms round-trip (network + compute)
- TEI local: ~20-50ms (no network, optimized inference)

**Deployment options**:
1. **TEI sidecar**: Docker container alongside context-service
2. **FastEmbed in-process**: Python library, ONNX runtime
3. **Hybrid**: TEI for production, FastEmbed for tests

**Matryoshka compatibility**:
- Nomic v1.5 trained with MRL (64, 128, 256, 512, 768 dims)
- Truncate to 512 dims at query time
- Document vectors remain 768-dim in Qdrant
- Qdrant handles dimension mismatch via padding/truncation

**Config change**:
```yaml
# config/models.yaml
tiers:
  balanced:
    embeddings:
      provider: vertex_ai
      model: text-embedding-005
      dimensions: 768
    query_embeddings:  # NEW
      provider: tei
      model: nomic-ai/nomic-embed-text-v1.5
      dimensions: 512
```

### 3. Tiered Result Cache

**Why in-process, not Redis**:
- Search results are small (list of UUIDs + scores, ~1KB)
- Short TTLs (5-60 min) don't benefit from persistence
- Avoids Redis round-trip on hot path
- Each pod has its own query patterns

**Implementation**:
```python
from cachetools import TTLCache

LAYER_TTLS = {
    "memory": 300,      # 5 min
    "knowledge": 3600,  # 1 hour
    "wisdom": 1800,     # 30 min
    "intelligence": 0,  # no cache
}

result_caches: dict[str, TTLCache] = {
    layer: TTLCache(maxsize=10000, ttl=ttl)
    for layer, ttl in LAYER_TTLS.items()
    if ttl > 0
}
```

**Invalidation via version tags**:
```python
# On any Knowledge write to silo:
await redis.incr(f"silo:{silo_id}:knowledge_version")

# Cache key includes version:
def cache_key(query_hash: str, layer: str, silo_id: str) -> str:
    if layer in ("wisdom", "knowledge"):
        version = await redis.get(f"silo:{silo_id}:knowledge_version") or 0
        return f"{query_hash}:{layer}:{silo_id}:{version}"
    return f"{query_hash}:{layer}:{silo_id}"
```

**Cross-layer queries**:
```python
async def recall_multi_layer(query: str, layers: list[str], silo_id: str):
    # Fetch from each layer's cache
    results = await asyncio.gather(*[
        get_cached_or_search(query, layer, silo_id)
        for layer in layers
    ])
    # Merge and rerank (cheap, ~10ms)
    merged = flatten(results)
    return await rerank(query, merged)
```

### 4. Qdrant Optimizations

**Scalar quantization**:
```python
# On collection creation
client.create_collection(
    collection_name="nodes",
    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
    quantization_config=ScalarQuantization(
        scalar=ScalarQuantizationConfig(
            type=ScalarType.INT8,
            always_ram=True,  # Keep quantized vectors in RAM
        )
    ),
)
```

**Hybrid search (future)**:
```python
# Add sparse vectors for BM25-style retrieval
vectors_config={
    "dense": VectorParams(size=512, distance=Distance.COSINE),
    "sparse": SparseVectorParams(),  # SPLADE or BM25
}

# Search with RRF fusion
results = client.query_points(
    collection_name="nodes",
    prefetch=[
        Prefetch(query=dense_vector, using="dense", limit=100),
        Prefetch(query=sparse_vector, using="sparse", limit=100),
    ],
    query=FusionQuery(fusion=Fusion.RRF),
    limit=top_k,
)
```

## Response Metadata

Add cache transparency to recall responses:

```python
{
    "results": [...],
    "cache_meta": {
        "embedding_cached": true,
        "result_cached": false,
        "cached_at": null,
        "layer_ttls": {"knowledge": 3600, "wisdom": 1800},
        "knowledge_version": 42
    }
}
```

**Freshness control**:
```python
async def recall(
    query: str,
    layers: list[str] | None = None,
    bypass_cache: bool = False,  # Force fresh results
    max_age_seconds: int | None = None,  # Reject cache older than this
) -> dict:
    ...
```

## Latency Targets

| Path | Current | Target | How |
|------|---------|--------|-----|
| Hot (all cached) | N/A | <20ms | Result cache hit |
| Warm (embedding cached) | ~200ms | <100ms | Skip embedding, search + rerank |
| Cold (nothing cached) | ~700ms | <200ms | TEI (50ms) + search (50ms) + rerank (50ms) |

## Implementation Phases

### Phase 1: Embedding Cache + TEI (High ROI)
1. Add Redis embedding cache layer
2. Deploy TEI sidecar or integrate FastEmbed
3. Update `_context_query` to check cache before embedding
4. Measure latency improvement

### Phase 2: Tiered Result Cache
1. Add in-process LRU caches per layer
2. Implement version-based invalidation
3. Add cross-layer composition logic
4. Add `cache_meta` to responses

### Phase 3: Qdrant Optimizations
1. Enable scalar quantization on existing collection
2. Test Matryoshka 512-dim compatibility
3. Add sparse vectors for hybrid search (if needed)

### Phase 4: Similarity Cache (Optional)
1. Maintain index of recent query embeddings
2. On cache miss, check cosine similarity
3. Reuse embedding if > 0.95 similarity

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Stale Knowledge results (1hr TTL) | `bypass_cache` param, `cache_meta` transparency |
| TEI availability | Fallback to Vertex, circuit breaker |
| Cache stampede on cold start | Single-flight pattern (coalesce concurrent requests) |
| Matryoshka quality loss at 512-dim | Benchmark on Somnus scenarios before rollout |
| Cross-layer composition overhead | Rerank is cheap (~10ms), acceptable |

## Success Metrics

- p50 recall latency: <100ms (from ~700ms)
- p95 recall latency: <250ms
- Embedding cache hit rate: >60% after warm-up
- Result cache hit rate: >30% for Knowledge layer
- No regression on Somnus accuracy benchmarks

## References

- [DeepSeek V4 Engram architecture](https://arxiv.org/abs/2601.07372) - O(1) lookup inspiration
- [Matryoshka Representation Learning](https://arxiv.org/abs/2205.13147) - MRL technique
- [Nomic Embed v1.5](https://www.nomic.ai/news/nomic-embed-matryoshka) - MRL support
- [HuggingFace TEI](https://github.com/huggingface/text-embeddings-inference) - Fast embedding server
- [Qdrant Scalar Quantization](https://qdrant.tech/documentation/guides/quantization/) - Storage optimization
- [Semantic Caching for LLMs](https://arxiv.org/abs/2504.02268) - Cache threshold tuning
