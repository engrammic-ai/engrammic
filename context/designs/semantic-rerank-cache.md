# Design: Semantic Rerank Cache

**Problem**: Vertex AI reranking takes ~600ms per call, exceeding our 500ms slow_tool threshold.

**Solution**: Cache rerank results by semantic similarity of queries, not just exact match.

## Key Insight

Queries with similar *intent* will produce similar rerank orderings for the same document set. If we've already reranked docs D1-D7 for "what was rejected?", we can reuse those scores for "what got rejected?" or "which items were rejected?".

## Design

### Two-Level Cache

```
Level 1: Exact query-docset cache (fast, O(1))
  Key: hash(query + sorted(doc_ids))
  Value: [(doc_id, score), ...]
  TTL: 5 minutes

Level 2: Semantic query cache (slower, requires embedding lookup)
  Key: query_embedding (stored in Qdrant collection)
  Metadata: {doc_ids_hash, scores, created_at}
  Similarity threshold: 0.95 cosine
```

### Flow

```
rerank(query, docs) ->
  1. Check L1 (exact match)
     - Hit: return cached scores
     - Miss: continue

  2. Check L2 (semantic match)
     - Embed query (already have this from vector search)
     - Search semantic cache collection for similar queries
       that also have same doc_ids_hash
     - If found with similarity >= 0.95: return cached scores
     - Miss: continue

  3. Call Vertex AI reranker
     - Store result in both L1 and L2
     - Return scores
```

### Why This Works

1. **Same docs required**: We only reuse scores when the exact same documents are being reranked. The doc_ids_hash in L2 metadata ensures this.

2. **High similarity threshold**: 0.95 cosine is very strict - only near-paraphrases match. "what was rejected" ↔ "what got rejected" but NOT "what was approved".

3. **Query embedding is free**: We already compute query embeddings for vector search. Reuse them for semantic cache lookup.

4. **Small collection**: The semantic cache is per-silo, storing only recent queries. Qdrant search over 1000 vectors takes <5ms.

### Implementation

```python
class SemanticRerankCache:
    """Two-level cache for rerank results."""

    def __init__(
        self,
        qdrant: QdrantClient,
        collection_name: str = "rerank_cache",
        similarity_threshold: float = 0.95,
        l1_ttl_seconds: int = 300,
        l2_max_entries: int = 1000,
    ):
        self._qdrant = qdrant
        self._collection = collection_name
        self._threshold = similarity_threshold
        self._l1 = TTLCache(maxsize=1000, ttl=l1_ttl_seconds)

    def _doc_ids_hash(self, doc_ids: list[str]) -> str:
        return hashlib.sha256(",".join(sorted(doc_ids)).encode()).hexdigest()[:16]

    def _l1_key(self, query: str, doc_ids: list[str]) -> str:
        return f"{hashlib.sha256(query.lower().encode()).hexdigest()[:16]}:{self._doc_ids_hash(doc_ids)}"

    async def get(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        silo_id: str,
    ) -> list[tuple[str, float]] | None:
        """Try to get cached rerank scores.
        
        Returns list of (doc_id, score) if cache hit, None otherwise.
        """
        # L1: exact match
        l1_key = self._l1_key(query, doc_ids)
        if l1_key in self._l1:
            record_cache_hit("rerank_l1", silo_id=silo_id)
            return self._l1[l1_key]

        # L2: semantic match
        doc_hash = self._doc_ids_hash(doc_ids)
        results = await self._qdrant.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            query_filter=Filter(
                must=[
                    FieldCondition(key="silo_id", match=MatchValue(value=silo_id)),
                    FieldCondition(key="doc_ids_hash", match=MatchValue(value=doc_hash)),
                ]
            ),
            limit=1,
            score_threshold=self._threshold,
        )

        if results and results[0].score >= self._threshold:
            scores = results[0].payload["scores"]
            # Populate L1 for next exact match
            self._l1[l1_key] = scores
            record_cache_hit("rerank_l2", silo_id=silo_id)
            return scores

        record_cache_miss("rerank", silo_id=silo_id)
        return None

    async def set(
        self,
        query: str,
        query_embedding: list[float],
        doc_ids: list[str],
        scores: list[tuple[str, float]],
        silo_id: str,
    ) -> None:
        """Store rerank results in both cache levels."""
        l1_key = self._l1_key(query, doc_ids)
        self._l1[l1_key] = scores

        # L2: store in Qdrant for semantic matching
        point_id = str(uuid.uuid4())
        await self._qdrant.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(
                    id=point_id,
                    vector=query_embedding,
                    payload={
                        "silo_id": silo_id,
                        "doc_ids_hash": self._doc_ids_hash(doc_ids),
                        "scores": scores,
                        "query": query,  # for debugging
                        "created_at": time.time(),
                    },
                )
            ],
        )
```

### Integration Point

In `_apply_reranking()` in `context_query.py`:

```python
async def _apply_reranking(
    query: str,
    query_embedding: list[float],  # NEW: pass from caller
    results: list[Any],
    settings: Any,
    silo_id: str,  # NEW: for cache scoping
) -> tuple[list[Any], bool]:
    if not settings.reranking.enabled or len(results) <= 1:
        return results, False

    doc_ids = [str(r.node_id) for r in results]

    # Check semantic cache first
    cache = get_rerank_cache()
    cached_scores = await cache.get(query, query_embedding, doc_ids, silo_id)
    if cached_scores is not None:
        # Reorder results by cached scores
        id_to_result = {str(r.node_id): r for r in results}
        score_map = dict(cached_scores)
        reordered = sorted(results, key=lambda r: score_map.get(str(r.node_id), 0), reverse=True)
        return reordered, False

    # Cache miss: call Vertex AI
    reranked = await reranker.rerank(...)
    
    # Store in cache
    scores = [(r.node_id, r.score) for r in reranked]
    await cache.set(query, query_embedding, doc_ids, scores, silo_id)
    
    return reranked_results, False
```

### Cache Collection Setup

```python
# One-time setup in Qdrant
await qdrant.create_collection(
    collection_name="rerank_cache",
    vectors_config=VectorParams(size=768, distance=Distance.COSINE),
)
await qdrant.create_payload_index(
    collection_name="rerank_cache",
    field_name="silo_id",
    field_schema=PayloadSchemaType.KEYWORD,
)
await qdrant.create_payload_index(
    collection_name="rerank_cache",
    field_name="doc_ids_hash",
    field_schema=PayloadSchemaType.KEYWORD,
)
```

### Eviction Strategy

- **L1**: TTL-based (5 min), in-process TTLCache
- **L2**: Keep newest 1000 entries per silo. Run cleanup via SAGE groundskeeper:
  ```python
  # Delete oldest entries when count > 1000
  await qdrant.delete(
      collection_name="rerank_cache",
      points_selector=FilterSelector(
          filter=Filter(must=[
              FieldCondition(key="silo_id", match=MatchValue(value=silo_id)),
          ])
      ),
      # order by created_at, limit to oldest N
  )
  ```

### Expected Impact

| Scenario | Current | With Cache |
|----------|---------|------------|
| Exact repeat query | ~600ms | <1ms (L1) |
| Paraphrased query, same docs | ~600ms | <20ms (L2 + embed) |
| New query or different docs | ~600ms | ~600ms |

Estimated cache hit rate: 40-60% (based on query pattern analysis showing high intent repetition).

### Risks

| Risk | Mitigation |
|------|------------|
| Stale cache returns wrong order | Short TTL (5 min), invalidate on knowledge version bump |
| L2 search adds latency on miss | L2 search is <5ms, acceptable overhead |
| Different doc order for same doc set | doc_ids_hash is sorted, order-independent |

### Open Questions

1. Should L2 be per-silo or global? (Currently per-silo for isolation)
2. Should we warm cache on silo creation with common queries?
3. Should knowledge version changes invalidate rerank cache? (Probably yes)

## Files to Change

| File | Change |
|------|--------|
| `src/context_service/cache/rerank_cache.py` | NEW: SemanticRerankCache class |
| `src/context_service/mcp/tools/context_query.py` | Wire cache into `_apply_reranking` |
| `src/context_service/config/settings.py` | Add rerank cache settings |
| `tests/cache/test_rerank_cache.py` | NEW: unit tests |
