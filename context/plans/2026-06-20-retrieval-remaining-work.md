# Retrieval: Remaining Work

**Date:** 2026-06-20
**Status:** Spec

## What's Shipped

| Feature | Commit | Notes |
|---------|--------|-------|
| FusionRetriever (4-channel) | `b4954a61` | Semantic + BM25 + Temporal + PPR |
| MCP wiring | `a461ef20` | `context_query.py` uses FusionRetriever |
| RRF fusion | `b83390f7` | Scores normalized 0-1 |
| Epistemic fusion | `e10fa003` | Confidence/conflict scoring post-rerank |
| Trigram/BM25 | `8d1ff82b` | Full-text search channel |
| Temporal channel | `b4954a61` | NL parsing + recency decay |
| Hybrid search default | settings.py | `hybrid_search_enabled=True` |
| Hard query detection | query_classifier.py | Question words, possessives, value-seeking |

## What's NOT Shipped

### 1. Write-time Semantic Dedup (from unified-recall-and-write-dedup.md)

**Problem:** Agents are told to "recall before storing" but server doesn't enforce or assist. Duplicates proliferate.

**Solution:** Add `_check_semantic_duplicates()` at write time:
- Reuse embedding computed for the write (no extra embed call)
- ANN search for similar nodes (top 3)
- Return `potential_duplicates` field in response when similarity > 0.85
- Optional: auto-supersede when similarity > 0.92

**Behavior modes (per silo config):**
- `warn` (default): Store succeeds, response includes warning
- `soft_block`: Store succeeds only with `acknowledge_duplicates=True`
- `hard_block`: Store fails with 409, must pass `supersedes`
- `auto_supersede`: Auto-create supersession edge for > 0.92 match

**Effort:** 3-4 hours

### 2. QuIM-RAG Question Generation (from recall-quality-improvement.md)

**Problem:** Query-answer asymmetry kills retrieval. User asks "What was my 5K time?" but stored content says "hoping to beat my personal best of 25:50".

**Solution:** At index time, generate questions the content answers:
- `ExpansionGenerator` exists at `expansion/generator.py`
- Currently generates "predicted search queries"
- Update prompt to explicitly generate questions

**Current prompt location:** `expansion/generator.py`

**New prompt:**
```
Given the following content, generate 3-5 questions that a user might ask
where this content would be the answer. Focus on value-seeking questions
(what, when, where, how much, who).

Content: {content}

Questions (one per line):
```

**Effort:** 1-2 hours (prompt update + verification)

### 3. sage.recall Cleanup

**Finding:** `sage/recall.py` has **zero callers** in production code. It's dead code from the brain architecture spec that was never wired in.

MCP recall uses: `recall.py` → `context_recall.py` → `context_query.py` → `FusionRetriever`

**Action:** Delete `sage/recall.py` and remove from `sage/__init__.py` exports.

**What sage.recall has that we might want:**
- `ConfidenceBreakdown` dataclass — already in FusionRetriever via epistemic_fusion
- `RecallOptions` dataclass — covered by FusionRetriever params
- PPR scoring constants — already in `retrieval/ppr.py`
- Layer enum — already in db/schema.py

**Effort:** 30 min (delete + verify no breakage)

### 4. Answer Fragment Expansion (lower priority)

**Problem:** Query expansion generates synonyms but not answer patterns.

**Solution:** Extend `QueryExpander` to also generate how an answer might be phrased:
```
Query: "What was my 5K time?"
Fragments: ["my time was", "personal best of", "finished in", "ran a"]
```

**Effort:** 2-3 hours

## Priority Order

1. **Write-time dedup** — highest impact, prevents garbage accumulation
2. **QuIM-RAG prompt** — quick win, fixes query-answer asymmetry
3. **sage.recall decision** — cleanup, reduces confusion
4. **Answer fragments** — incremental improvement

## Dependencies

- Write-time dedup: embedding service available at write time (already is)
- QuIM-RAG: expansion model configured (check `expansion_llm_model` in settings)
- sage.recall: decision on brain architecture direction

## Open Questions

1. Is sage.recall actually used anywhere? Check callers.
2. What's the expansion model configured? Flash-tier sufficient?
3. Should dedup check be async (fire-and-forget warning) or sync (block response)?
