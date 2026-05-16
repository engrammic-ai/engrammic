# Semantic Reranking Spec

## Decision Log

### Options Considered

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| **A: Cross-encoder only** | Vertex AI reranker on every search | Fast (~100ms), simple | Fails deep semantic equivalence (4/5 accuracy) |
| **B: LLM reranker only** | Gemini Flash scores each result | 5/5 accuracy | 2-6s latency, too slow |
| **C: Query expansion always** | LLM expands every query before search | Good accuracy | ~500ms added to every query |
| **D: LLM rerank fallback** | Cross-encoder first, LLM if low confidence | Good accuracy | Hard to detect "low confidence" reliably |
| **E: Hybrid (chosen)** | Detect hard queries, LLM expand those only, cross-encoder rerank all | Best balance | Slightly more complex |

### Decision

**Option E: Hybrid approach with hard query detection + cached LLM expansion + cross-encoder reranking**

Rationale:
- Cross-encoders handle 80%+ of queries well and are fast
- LLM reasoning only needed for abstract/inferential queries
- Caching amortizes LLM cost to near-zero over time
- Maintains <250ms latency for most queries, <750ms for hard queries (cold)

### Alternatives Rejected

1. **Cohere Rerank 3.5**: Same accuracy as Vertex (4/5), requires separate AWS billing
2. **Jina Reranker**: Worst accuracy (1/5), ranked correct answer last
3. **Fine-tuning BGE-reranker**: High effort, unclear if it would solve the problem
4. **NLI classifier**: Would need custom integration, unclear accuracy gains
5. **ColBERT/late-interaction models**: Potentially better semantic matching than cross-encoders, but requires infrastructure changes (separate index), not supported by LiteLLM
6. **Hybrid scoring (weighted fusion)**: Combine cross-encoder score with original vector score. Adds complexity, unclear benefit over pure reranking. Could revisit if reranking alone underperforms.

## Problem

Hybrid search (dense + SPLADE) finds **similar** text, but we need text that **answers** or **entails** the query. Example:

| Query | Stored | Problem |
|-------|--------|---------|
| "what was rejected?" | "failure to warn theory is no longer viable" | Entailment, not similarity |

SPLADE expands terms lexically but "no longer viable" is a different lexical space than "rejected".

## Evaluation Results

Tested multiple rerankers on 5 entailment cases:

| Model | Accuracy | rejected=viable? | Latency |
|-------|----------|------------------|---------|
| Vertex AI semantic-ranker-default | 4/5 | No | ~100ms |
| Vertex AI semantic-ranker-fast | 3/5 | No | ~50ms |
| Cohere Rerank 3.5 (Bedrock) | 4/5 | No | ~100ms |
| Jina Reranker v2 | 1/5 | No | ~100ms |
| **Gemini Flash (LLM)** | **5/5** | **Yes** | ~2-6s |

Cross-encoders fail on deep semantic equivalence. LLMs handle it but are too slow for every query.

## Solution: Hybrid Approach

```
Query → Hard query? → Yes → LLM expand (cached) → Search → Vertex rerank → Results
                    → No  → Search → Vertex rerank → Results
```

- **Normal path**: Fast cross-encoder reranking (~250ms)
- **Hard queries**: LLM query expansion + reranking (~750ms first time, ~250ms cached)

## Architecture

### 1. Hard Query Detection

Location: `src/context_service/reranking/query_classifier.py`

**Known limitation**: This regex-based classifier is intentionally simple for MVP. It will have false negatives (e.g., "which approaches were abandoned?" won't trigger expansion). Plan to evolve to LLM-based classifier or trained model based on production query logs.

```python
import re

ABSTRACT_VERBS = {
    "rejected", "approved", "denied", "accepted", "failed", "succeeded",
    "postponed", "cancelled", "confirmed", "dismissed", "granted",
    "abandoned", "dropped", "removed", "added", "changed", "decided",
}

QUESTION_PATTERNS = [
    r"^what (was|were|got|is|are) \w+\??$",  # "what was rejected?"
    r"^why did .+\??$",                       # "why did X fail?"
    r"^(is|are|was|were) .+ (approved|rejected|denied)\??$",
    r"^which .+ (was|were|got) \w+\??$",     # "which approach was abandoned?"
]

def is_hard_query(query: str) -> bool:
    """Detect queries requiring semantic reasoning.
    
    Note: Intentionally conservative. False negatives are logged for iteration.
    """
    query_lower = query.lower().strip()
    words = query_lower.split()
    
    # Short queries with abstract verbs
    if len(words) <= 5 and any(w in ABSTRACT_VERBS for w in words):
        return True
    
    # Question patterns that need inference
    for pattern in QUESTION_PATTERNS:
        if re.match(pattern, query_lower):
            return True
    
    return False
```

**Evolution path**: After collecting query logs, train a lightweight classifier or use LLM-based detection (cached). The current heuristic is a starting point, not the final solution.

### 2. Query Expansion Service

Location: `src/context_service/reranking/query_expander.py`

```python
from context_service.cache.redis_client import RedisClient

EXPANSION_PROMPT = '''Expand this search query with semantically equivalent phrases.
The goal is to find documents that ANSWER the query, even if they use different words.

Query: {query}

Return JSON:
{{"expanded": "original query OR synonym1 OR 'equivalent phrase' OR synonym2"}}

Examples:
- "rejected" → "rejected OR denied OR dismissed OR 'no longer viable' OR 'not accepted'"
- "approved" → "approved OR accepted OR 'green light' OR granted OR confirmed"
- "failed" → "failed OR 'did not succeed' OR 'did not complete' OR unsuccessful"
'''

class QueryExpander:
    """LLM-based query expansion with Redis caching."""
    
    CACHE_PREFIX = "qexp:"
    CACHE_TTL = 86400 * 7  # 7 days
    
    def __init__(self, llm_model: str, redis: RedisClient):
        self._model = llm_model
        self._redis = redis
    
    async def expand(self, query: str) -> str:
        """Expand query with semantic equivalents. Returns original if expansion fails."""
        cache_key = f"{self.CACHE_PREFIX}{self._normalize(query)}"
        
        # Check cache
        cached = await self._redis.get(cache_key)
        if cached:
            return cached
        
        # LLM expansion
        try:
            expanded = await self._llm_expand(query)
            await self._redis.set(cache_key, expanded, ex=self.CACHE_TTL)
            return expanded
        except Exception as e:
            logger.warning("query_expansion_failed", query=query, error=str(e))
            return query  # fallback to original
    
    async def _llm_expand(self, query: str) -> str:
        prompt = EXPANSION_PROMPT.format(query=query)
        response = await litellm.acompletion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        return data["expanded"]
    
    def _normalize(self, query: str) -> str:
        """Normalize query for cache key.
        
        Intentionally collapses variations:
        - "What was rejected?" → "what was rejected?"
        - "what was rejected" → "what was rejected"
        - "WHAT WAS REJECTED?" → "what was rejected?"
        
        This means "what was rejected?" and "what was rejected" share a cache
        entry. This is acceptable since expansions should be the same regardless
        of trailing punctuation.
        """
        return query.lower().strip()
```

### 3. Cross-Encoder Reranker

Location: `src/context_service/reranking/reranker.py`

```python
class LiteLLMReranker:
    """Cross-encoder reranking via Vertex AI."""
    
    def __init__(self, model: str = "vertex_ai/semantic-ranker-default@latest"):
        self._model = model
    
    async def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int = 10,
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query."""
        if not documents:
            return []
        
        try:
            response = await litellm.arerank(
                model=self._model,
                query=query,
                documents=documents,
                top_n=top_k,
            )
            return [
                RerankResult(
                    node_id=node_ids[r["index"]],
                    score=r["relevance_score"],
                    original_rank=r["index"],
                )
                for r in response.results
            ]
        except Exception as e:
            logger.warning("reranking_failed", error=str(e))
            # Fallback: return original order
            return [
                RerankResult(node_id=nid, score=1.0 - i * 0.01, original_rank=i)
                for i, nid in enumerate(node_ids[:top_k])
            ]
```

### 4. Unified Recall Pipeline

Location: `src/context_service/engine/recall.py`

```python
@dataclass
class RecallConfig:
    rerank_enabled: bool = True
    expand_hard_queries: bool = True
    rerank_pool_size: int = 50
    final_limit: int = 10


class RecallPipeline:
    """Unified recall with optional expansion and reranking."""
    
    def __init__(
        self,
        vector_store: QdrantClient,
        embedding_service: LiteLLMEmbeddingService,
        reranker: LiteLLMReranker | None,
        expander: QueryExpander | None,
    ):
        self._vector_store = vector_store
        self._embeddings = embedding_service
        self._reranker = reranker
        self._expander = expander
    
    async def recall(
        self,
        query: str,
        silo_id: str,
        config: RecallConfig = RecallConfig(),
    ) -> list[SearchResult]:
        """Execute recall with optional expansion and reranking."""
        
        effective_query = query
        expanded = False
        
        # Step 1: Query expansion for hard queries
        if config.expand_hard_queries and self._expander and is_hard_query(query):
            effective_query = await self._expander.expand(query)
            expanded = True
            logger.info("query_expanded", original=query, expanded=effective_query)
        
        # Step 2: Hybrid search
        pool_size = config.rerank_pool_size if config.rerank_enabled else config.final_limit
        results = await self._search(effective_query, silo_id, limit=pool_size)
        
        # Step 3: Reranking
        if config.rerank_enabled and self._reranker and len(results) > config.final_limit:
            # IMPORTANT: Rerank using EXPANDED query, not original.
            # Rationale: The expanded query contains semantic equivalents that the
            # cross-encoder should use when scoring. If we search with "rejected OR
            # 'no longer viable'" but rerank with just "rejected", the cross-encoder
            # won't know to score "no longer viable" documents highly.
            results = await self._rerank(effective_query, results, config.final_limit)
        
        return results[:config.final_limit]
    
    async def _search(self, query: str, silo_id: str, limit: int) -> list[SearchResult]:
        """Execute hybrid search."""
        embedding = await self._embeddings.embed_query(query)
        # ... sparse encoding, search, etc.
        return await self._vector_store.search(
            vector=embedding,
            silo_id=silo_id,
            limit=limit,
            search_mode="hybrid",
        )
    
    async def _rerank(
        self,
        query: str,
        results: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """Apply cross-encoder reranking."""
        documents = [r.payload.get("content", "") for r in results]
        node_ids = [r.node_id for r in results]
        
        reranked = await self._reranker.rerank(query, documents, node_ids, top_k=limit)
        
        id_to_result = {r.node_id: r for r in results}
        return [
            SearchResult(
                node_id=rr.node_id,
                score=rr.score,
                payload=id_to_result[rr.node_id].payload,
            )
            for rr in reranked
        ]
```

## Config Integration

### models.yaml

```yaml
tiers:
  balanced:
    # ... existing ...
    reranker:
      provider: vertex_ai
      model: semantic-ranker-default@latest
    query_expander:
      provider: vertex
      model: gemini-2.5-flash

  economy:
    reranker:
      provider: vertex_ai
      model: semantic-ranker-fast@latest
    query_expander:
      provider: vertex
      model: gemini-2.5-flash

  self_hosted:
    reranker: null  # not available
    query_expander:
      provider: vllm
      model: Qwen/Qwen3-7B
```

### settings.yaml

```yaml
recall:
  rerank_enabled: true
  expand_hard_queries: true
  rerank_pool_size: 50
  expansion_cache_ttl_days: 7
```

### Environment Variables

```bash
RERANK_ENABLED=true
EXPAND_HARD_QUERIES=true
```

## Performance

| Path | Latency | When |
|------|---------|------|
| Normal query | ~250ms | 80% of queries |
| Hard query (cached) | ~250ms | After first occurrence |
| Hard query (cold) | ~750ms | First occurrence |

### Breakdown (Normal)

| Stage | Target |
|-------|--------|
| Hybrid search (top-50) | < 150ms |
| Reranking (50 -> 10) | < 100ms |
| **Total** | < 250ms |

### Breakdown (Hard, Cold)

| Stage | Target |
|-------|--------|
| Hard query detection | < 1ms |
| LLM expansion | < 500ms |
| Hybrid search (top-50) | < 150ms |
| Reranking (50 -> 10) | < 100ms |
| **Total** | < 750ms |

## Caching Strategy

### Query Expansion Cache (Redis)

```
Key: qexp:{normalized_query}
Value: expanded query string
TTL: 7 days
```

Examples:
```
qexp:what was rejected? → "rejected OR denied OR dismissed OR 'no longer viable'"
qexp:what got approved? → "approved OR accepted OR 'green light' OR granted"
```

### Cache Warming (Optional)

Pre-populate common patterns on startup:

```python
COMMON_EXPANSIONS = {
    "rejected": "rejected OR denied OR dismissed OR 'no longer viable' OR 'not accepted'",
    "approved": "approved OR accepted OR 'green light' OR granted OR confirmed",
    "failed": "failed OR 'did not succeed' OR 'did not complete' OR unsuccessful",
    "postponed": "postponed OR delayed OR 'pushed back' OR deferred OR rescheduled",
}
```

## MCP Tool Changes

`context_recall` parameters:

```python
class RecallParams(BaseModel):
    query: str
    mode: Literal["search", "flat", "graph"] = "search"
    limit: int = 10
    rerank: bool = True           # enable cross-encoder reranking
    expand_query: bool = True     # enable LLM expansion for hard queries
```

## Fallback Behavior

Explicit fallback chain for each component:

### Query Expansion Fallbacks

| Condition | Behavior |
|-----------|----------|
| Redis down, LLM available | Expand without cache (slower, ~500ms), log warning |
| Redis down, LLM fails | Use original query, log error |
| Redis up, LLM fails | Use original query, log error, do NOT cache failure |
| LLM timeout (>2s) | Use original query, log timeout |

### Reranker Fallbacks

| Condition | Behavior |
|-----------|----------|
| Vertex AI unavailable | Return original search order (by vector score), log warning |
| Reranker timeout (>500ms) | Return original search order, log timeout |
| Empty documents (no content field) | Skip those docs in reranking, preserve their original rank |

### Combined Failure

If both expansion AND reranking fail, the system degrades to basic hybrid search - still functional, just less accurate on hard queries. This is acceptable for availability.

## Testing

### Unit Tests

1. `test_is_hard_query()` - classifier accuracy
2. `test_query_expander()` - expansion quality with mocked LLM
3. `test_reranker()` - reranking with mocked Vertex AI
4. `test_recall_pipeline()` - end-to-end with mocks

### Integration Tests

```python
@pytest.mark.integration
async def test_hard_query_finds_semantic_match():
    """The 'rejected = no longer viable' case."""
    # Store document
    await store("Failure to warn theory is no longer viable.")
    
    # Search with hard query
    results = await recall("what was rejected?")
    
    # Should find it
    assert len(results) > 0
    assert "no longer viable" in results[0].content
```

### Benchmark Tests

```python
@pytest.mark.benchmark
async def test_recall_latency():
    # Normal query: < 250ms
    # Hard query (cached): < 250ms
    # Hard query (cold): < 750ms
```

## Rollout

### Phase 1: Reranking Only
1. Add `LiteLLMReranker`
2. Wire into recall with `RERANK_ENABLED=false`
3. Test on staging
4. Flip to `true`

### Phase 2: Query Expansion
1. Add `QueryExpander` and `is_hard_query()`
2. Wire into recall with `EXPAND_HARD_QUERIES=false`
3. Monitor cache hit rate and latency
4. Flip to `true`

### Phase 3: Tuning
1. Expand `ABSTRACT_VERBS` based on observed failures
2. Warm cache with common patterns
3. Consider per-silo expansion customization

## Observability

### Metrics

```python
recall_latency_ms{path="normal|hard_cached|hard_cold"}
query_expansion_cache_hit_rate
reranking_fallback_count
hard_query_detection_count
hard_query_detection_rate  # hard_count / total_count - validate 20% assumption
```

### False Negative Detection

Log queries where reranking significantly reorders results but `is_hard_query()` returned false. These are candidates for expanding the classifier:

```python
if not is_hard and rerank_changed_top_result:
    logger.info(
        "potential_false_negative",
        query=query,
        original_top=original_results[0].node_id,
        reranked_top=reranked_results[0].node_id,
    )
```

Review these logs weekly to expand `ABSTRACT_VERBS` and `QUESTION_PATTERNS`.

### Tracing

Spans:
- `recall.classify_query`
- `recall.expand_query` (with cache hit/miss attribute)
- `recall.search`
- `recall.rerank`

## Known Limitations

### Out of Scope (v1)

1. **Multi-hop queries**: "What was rejected about the pricing strategy?" requires entity resolution + entailment. Current expansion handles single-concept queries only.
2. **Per-silo vocabulary**: Different silos may use different terminology. Current expansion is silo-agnostic.
3. **Negation chains**: "What wasn't rejected?" - complex negation not handled.

### Planned Improvements (v2+)

1. LLM-based hard query classifier (replace regex heuristics)
2. Per-silo expansion customization
3. Multi-hop query decomposition

## Cost Analysis

### Per 1000 Queries (Assuming 20% Hard Queries)

| Component | Calls | Cost |
|-----------|-------|------|
| Vertex Reranker | 1000 | ~$0.50 |
| Gemini Flash (expansion) | 200 (first time) | ~$0.02 |
| **Total** | | ~$0.52 |

After cache warm-up, expansion cost drops to near-zero.

**Note**: The 20% hard query rate is an estimate. Actual rate depends on user query patterns. Metric `hard_query_detection_count` should be monitored in production to validate this assumption and adjust cost projections.
