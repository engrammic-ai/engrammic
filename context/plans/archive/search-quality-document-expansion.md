# Brainstorm: Improving context_recall Search Quality

**Mode**: problem
**Date**: 2026-05-04

## Summary

Search failed because "checkpoint" and "queued" are semantically distant in embedding space despite being conceptually related in your domain (both describe task state). This is a **known fundamental IR problem called vocabulary mismatch** - not purely an embedding limitation.

## Research Findings

**Why embeddings don't "just work" for this:**
- Jina v2 had documented failure: "Misleading Syntactic Similarities" - favors high syntactic overlap over semantic relevance
- SPLADE (sparse) needs token overlap - "checkpoint" and "queued" share none
- Dense embeddings capture general semantics but miss domain-specific concept relationships
- This is why hybrid search exists, but hybrid alone doesn't solve vocabulary mismatch

**2026 best practice:** Hybrid (dense+sparse) + query/document expansion + re-ranking

**New discovery:** Jina v4 has a `text-matching` adapter (CoSENT loss) for semantic similarity. We're using `retrieval.query` - might be suboptimal.

## Key Insights

1. **Root Cause**: Vocabulary mismatch is fundamental to IR, not a bug. No semantic bridge between user intent ("checkpoint") and stored terminology ("queued task").

2. **Failure Pattern**: Recurs when users query with implied concepts, domain jargon, or abstract nouns requiring inference.

3. **Multiple Levers**: Jina adapter switch (quick test), query expansion (medium), document expansion (write-time).

## Recommendations (Ranked, Vendor-Agnostic)

### 1. Query-Time LLM Rewriting (Primary)
Add pre-processing in `context_recall.py` before search:
```
"custodian checkpoint" → "custodian checkpoint stress test task queued paused status"
```
- Effort: 1-2 days
- Latency cost: 200-500ms (can be parallelized with embedding)
- No reindexing needed

### 2. Document Expansion at Write-Time (Primary)
Store predicted queries in separate `expansion` field - no content pollution.

**Architecture:**
```
On store:
  1. LLM generates predicted queries from content
  2. Store in `expansion` payload field (user never sees)
  3. SPLADE encodes content + expansion → sparse vector
  4. Dense encodes content only → dense vector

On recall:
  5. Search matches both vectors via RRF
  6. Return `content` only, never expose `expansion`
```

- Effort: 2-3 days
- Zero query-time latency
- Clean data separation
- Requires backfill script for existing nodes

### 3. Re-Ranking Layer
Add lightweight re-ranker after initial retrieval (Cohere, Jina reranker, or LLM).
- Effort: 2-3 days
- Boosts precision on borderline matches
- Additional latency but only on top-K results

## Open Questions

1. Does switching Jina adapter to `text-matching` improve recall? (Quick experiment)
2. LLM rewriting latency - can we parallelize with embedding to hide cost?
3. Backfill strategy for document expansion - incremental or batch?

## Critical Files

- `src/context_service/services/context.py` - modify `store()` to generate expansions
- `src/context_service/embeddings/splade.py` - encode content+expansion
- `src/context_service/engine/qdrant_store.py` - add expansion field to schema
- `src/context_service/llm/` - expansion generator (new or reuse existing client)

## Next Steps

1. [ ] Build vocab mismatch test harness (baseline measurement)
2. [ ] Add `expansion` field to Qdrant schema
3. [ ] Implement LLM expansion generator (prompt: predict queries for content)
4. [ ] Modify SPLADE encoding to include expansion field
5. [ ] Write backfill script for existing nodes
6. [ ] Measure recall improvement vs baseline

## Sources

- [Semantic approaches for query expansion - PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC11935759/)
- [Jina Embeddings v4 - Task adapters](https://jina.ai/models/jina-embeddings-v4/)
- [TF-IDF vs Embeddings - PyImageSearch](https://pyimagesearch.com/2026/02/09/tf-idf-vs-embeddings-from-keywords-to-semantic-search/)
- [Doc2Query++ Document Expansion](https://arxiv.org/html/2510.09557v2)
