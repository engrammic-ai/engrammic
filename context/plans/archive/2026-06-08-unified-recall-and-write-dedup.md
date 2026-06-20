# Unified Recall and Write-time Dedup

**Date:** 2026-06-08
**Status:** Draft
**Goal:** Merge retrieval paths into sage.recall, add server-side semantic dedup at write time

## Problem

1. **Two retrieval paths**: `_context_query` (production, has reranking/caching) vs `sage.recall` (brain, has epistemic scoring) — neither complete
2. **No write-time semantic check**: Agents told to "recall before storing" but server doesn't enforce or assist
3. **Clustering is async-only**: No write-time cluster assignment or duplicate detection

## Proposed Solution

### Phase 1: Unified Recall

Merge into single `sage.recall.recall()` that has:

**From _context_query (keep):**
- Query expansion (LLM for hard queries)
- Result caching (Redis-backed, knowledge-version keyed)
- Reranking via cross-encoder
- Adaptive threshold filtering (compute_adaptive_threshold, silo threshold_overrides, min_threshold)

**From sage.recall (keep):**
- Layer-semantic scoring (`compute_recall_score`)
- State/temporal/confidence filtering
- PPR transitive scoring (graph diffusion) — boost only, not gate
- Lazy synthesis trigger
- Confidence breakdown (CITE-v2)

**Pipeline:**
```
query
  → expand (if hard query)
  → cache check
  → embed
  → vector search (over-fetch 3x)
  → filter (state, temporal, layer, confidence)
  → score (layer semantics + freshness + heat)
  → rerank (cross-encoder)
  → PPR boost (additive, not multiplicative — disconnected nodes keep rerank score)
  → adaptive threshold
  → cache write
  → return with confidence breakdown
```

**PPR behavior change:** Currently multiplies by 0.1 default for disconnected nodes, collapsing scores. Change to additive boost: `final_score = rerank_score + (ppr_boost * weight)` where weight ~ 0.2. Disconnected nodes keep their rerank score.

### Phase 2: Write-time Semantic Check

Add to `store_memory` and `store_claim`:

```python
async def _check_semantic_duplicates(
    content: str,
    silo_id: str,
    layer: str,
    embedding: list[float],  # REUSE from write path, don't re-embed
    warn_threshold: float = 0.85,
    auto_supersede_threshold: float = 0.92,
    top_k: int = 3,
) -> list[DuplicateCandidate]:
    """Quick semantic search before write.
    
    Returns potential duplicates above warn_threshold.
    Caller decides: reject, warn, or auto-supersede based on score.
    
    NOTE: Embedding passed in, not computed here — avoids double-embed cost.
    """
```

**Behavior options (configurable per silo):**
1. `warn` (default): Store succeeds, response includes `potential_duplicates` field
2. `soft_block`: Store succeeds only if agent passes `acknowledge_duplicates=True`
3. `hard_block`: Store fails with 409 Conflict, must pass `supersedes` to proceed
4. `auto_supersede`: If single match > 0.92, auto-create supersession edge

**Thresholds (two-tier):**
- 0.85-0.92: warn (similar but potentially distinct)
- 0.92+: auto-supersede candidate (likely duplicate)

**Layer-specific defaults:**
- Memory: `warn` only (observations can be intentionally similar)
- Knowledge/Wisdom: configurable, default `warn`

**Performance budget:** < 30ms for the check (ANN search only, embedding reused from write path)

### Phase 3: Write-time Cluster Hint (DEFERRED)

**Decision:** Skip write-time cluster assignment for now.

**Rationale:** 
- Leiden community detection uses different similarity metric than cosine threshold
- Write-time assignment at 0.7 cosine would conflict with Leiden refinement, causing thrash
- Async clustering via Custodian is working; immediate membership not critical path

**Future option (if needed):**
```python
# Use TENTATIVE_MEMBER_OF edge that Leiden explicitly reconsiders
await _add_tentative_cluster_membership(node_id, nearest_cluster_id)
```

For now, rely on existing async flow:
1. Write emits `UPDATE_CLUSTER_MEMBERSHIP` reaction
2. Dagster custodian runs Leiden periodically
3. Reaction task confirms membership after Leiden

## Implementation Order

**IMPORTANT:** Port features into sage.recall FIRST, wire MCP LAST. Avoids regression window.

### Phase 1: Unified Recall (atomic change)

1. **Port reranking into sage.recall** — add `_rerank_results()` using LiteLLMReranker
2. **Port adaptive threshold into sage.recall** — add `compute_adaptive_threshold`, silo overrides
3. **Port result caching into sage.recall** — add ResultCacheStore integration
4. **Port query expansion into sage.recall** — add `_maybe_expand_query()` for hard queries
5. **Fix PPR boost** — change from multiplicative to additive
6. **Wire recall MCP tool to sage.recall** — update `recall.py` to call `sage.recall.recall()`
7. **Validate against somnus benchmark** — must not regress from baseline
8. **Delete _context_query** — only after validation passes

### Phase 2: Write-time Dedup

9. **Add `_check_semantic_duplicates()`** — accepts pre-computed embedding
10. **Integrate into store_memory/store_claim** — after embed, before graph write
11. **Add silo-level dedup config** — mode per layer (warn/soft_block/hard_block)
12. **Update MCP tool responses** — include `potential_duplicates` field when relevant

### Phase 3: Cleanup

13. **Update mcp_tools.yaml** — ensure handler references are correct
14. **Delete dead code** — _context_recall routing, unused imports

## Testing

- **Phase 1 gate:** Somnus benchmark after step 7, before step 8. Must not regress from baseline.
- **Write latency:** p95 must stay < 300ms with dedup check (budget: 30ms for ANN search)
- **Duplicate detection:** Precision > 90% at 0.92 threshold on test set
- **Cache invalidation:** Verify knowledge_version bumps on all write scenarios (including supersession)

## Open Questions (RESOLVED)

1. ~~Should dedup check be opt-out per request?~~ **Yes** — add `skip_dedup=True` param for bulk imports
2. ~~Should we do dedup for Memory layer?~~ **Yes but warn-only** — observations can be intentionally similar
3. ~~What's the right threshold?~~ **Two-tier:** 0.85 warn, 0.92 auto-supersede

## Dependencies

- sage.recall already exists, just needs wiring
- Reranking code exists in `reranking/` module
- Caching code exists in `cache/` module
- Embedding service already available at write time
