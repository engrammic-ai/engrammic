# Recall Quality Improvement Plan

## Status: Draft (Reviewed 2026-06-05)

## Problem Statement

LongMemEval knowledge-update benchmark exposes a critical retrieval weakness: Engrammic scores **29%** vs **67%** baseline. The root cause is **question-answer asymmetry**:

- Query asks for VALUE/RESULT: "What was my 5K time?"
- Stored content states GOAL/INTENTION: "hoping to beat my personal best time of 25:50"
- Dense embeddings fail to bridge this structural gap

The benchmark is working correctly - it exposes a real retrieval quality issue.

## Research Context

2024-2025 RAG literature (QuIM-RAG, ColBERT v2, SPLADE++, HyDE) shows:
- ~35% of retrieval failures are query formulation issues
- BM25 still outperforms dense on exact identifiers and rare terms
- QuIM-RAG (question-to-question matching) eliminates asymmetry by design
- Hybrid search (dense + sparse) covers both semantic and lexical gaps

---

## Implementation Phases

### Phase 1: Enable Hybrid Search [Quick Win]

**Impact: HIGH | Effort: LOW | Risk: MEDIUM**

SPLADE infrastructure already exists but is disabled:
- `src/context_service/embeddings/splade.py` - full implementation present
- `src/context_service/engine/qdrant_store.py` - RRF fusion wired (L70-379)
- `src/context_service/config/settings.py:370` - `hybrid_enabled: bool = False`
- `src/context_service/config/settings.py:1081` - `hybrid_search_enabled: bool = False`

**Expected lift:** "25:50" matches "personal best time of 25:50" via BM25; "5K" matches "charity 5K run".

**Files to modify:**
- Flip `hybrid_enabled` and `hybrid_search_enabled` to `True` in settings
- Verify SPLADE model loads correctly (`prithivida/Splade_PP_en_v1`)

**RISK: Existing silos need recreation**
Silos created without hybrid mode lack sparse vector indices. Plan:
1. Add migration flag `recreate_silos_for_hybrid` (opt-in)
2. Document that new silos automatically get sparse indices
3. Provide CLI: `uv run ctx-admin silo rebuild --hybrid <silo_id>`

**Estimate:** 2-4 hours (including migration tooling)

---

### Phase 2: Expand Hard Query Detection [Done]

**Impact: MEDIUM | Effort: VERY LOW**

Code review confirms this is **already implemented**. `query_classifier.py` now:
- Treats all question-word queries as hard (L77-79)
- Catches possessive patterns ("my X")
- Catches value-seeking patterns ("how many/much/long")

No further work needed here.

---

### Phase 3: Index-Time Question Generation (QuIM-RAG) [Core Fix]

**Impact: VERY HIGH | Effort: MEDIUM | Risk: LOW**

At store time, generate questions the content answers:

```
Content: "hoping to beat my personal best time of 25:50"
Generated questions:
  - "What is my 5K personal best?"
  - "What time am I trying to beat?"
  - "What's my running goal?"
```

**KEY INSIGHT:** `ExpansionGenerator` already exists at `src/context_service/expansion/generator.py` and is wired into `context.py:store()` (line 117). The current prompt generates "predicted search queries" - this is conceptually identical to QuIM-RAG.

**Gap analysis:**
1. Current `ExpansionGenerator` output feeds SPLADE, but SPLADE is disabled
2. With Phase 1 (hybrid enabled), expansion output will automatically flow through
3. Prompt could be improved to explicitly generate questions, not just query terms

**Recommended changes:**

```python
# expansion/generator.py - update prompt
_PROMPT_TEMPLATE = """\
Given the following content, generate 3-5 questions that a user might ask \
where this content would be the answer. Focus on value-seeking questions \
(what, when, where, how much, who).

Content: {content}

Questions (one per line):"""
```

**Integration points (already wired, just need hybrid enabled):**
- `context.py:store()` - calls `ExpansionGenerator.generate()`
- Output concatenated to SPLADE input
- No changes needed to remember/learn/believe tools

**Verification:**
- Confirm `expansion_enabled: True` in settings (L1471)
- Confirm expansion model is configured in `config/models.yaml`

**Estimate:** 1-2 hours (prompt tuning + verification)

---

### Phase 4: Enhanced Query Expansion (Answer Fragments) [Incremental]

**Impact: MEDIUM | Effort: LOW**

Extend `QueryExpander` (reranking/query_expander.py) to also generate how an answer might be phrased:

```python
# Current:
"rejected" -> "rejected OR denied OR dismissed"

# Enhanced: Add answer fragment generation
# Query: "What was my 5K time?"
# Fragments: ["my time was", "personal best of", "finished in", "ran a"]
```

**Implementation:**
Add a second LLM call or extend the existing prompt to generate answer fragments alongside synonyms. Cache both under the same key.

**Risk:** Doubles LLM calls for hard queries. Mitigate with aggressive caching (current 7-day TTL is good).

**Estimate:** 2-3 hours

---

### Phase 5: Temporal Scoring Boost [Incremental]

**Impact: MEDIUM | Effort: LOW | Risk: LOW**

For knowledge-update queries, boost recent nodes over older ones. Apply decay to superseded nodes.

**Note:** Superseded nodes are already filtered in `context.py:query()`. This phase adds recency boost even among non-superseded nodes.

**Implementation:**
```python
# context.py:query() - add temporal multiplier to final score
age_days = (now - node.created_at).days
recency_boost = 1.0 / (1.0 + 0.01 * age_days)  # Half-life ~70 days
final_score = base_score * recency_boost
```

Make the decay configurable via `RetrievalTuning` settings.

**Estimate:** 2 hours

---

## Implementation Order (Recommended)

| Phase | Task | Est. | Dependencies | Expected Lift |
|-------|------|------|--------------|---------------|
| 1 | Enable hybrid search | 2-4h | Silo migration | +15-20% |
| 2 | Hard query detection | Done | None | (already shipped) |
| 3 | Question generation prompt | 1-2h | Phase 1 | +20-30% |
| 4 | Answer fragment expansion | 2-3h | Phase 2 | +5-10% |
| 5 | Temporal scoring | 2h | None | +5-10% |

**Total estimate:** 7-11 hours for Phases 1, 3, 4, 5

Phase 1 + 3 together should yield the majority of improvement.

---

## Critical File Index

**Recall flow:**
- `src/context_service/mcp/tools/recall.py` - entry point
- `src/context_service/mcp/tools/context_query.py` - search orchestration (L322: expansion, L395: reranking)
- `src/context_service/services/context.py:query()` - vector search + scoring (L1389-1563)
- `src/context_service/engine/qdrant_store.py` - RRF fusion for hybrid (L70-379)

**Index-time expansion (QuIM-RAG):**
- `src/context_service/expansion/generator.py` - Doc2Query generator (existing)
- `src/context_service/services/context.py:store()` - integration point (L143+)

**Reranking/expansion:**
- `src/context_service/reranking/query_classifier.py` - hard query detection (done)
- `src/context_service/reranking/query_expander.py` - LLM query expansion
- `src/context_service/reranking/reranker.py` - cross-encoder

**Config:**
- `src/context_service/config/settings.py` - `hybrid_enabled`, `hybrid_search_enabled`, `expansion_enabled`
- `src/context_service/embeddings/splade.py` - SPLADE encoder (existing)

---

## Testing Strategy

### Unit Tests
- `tests/reranking/test_query_classifier.py` - verify expanded patterns (already exists)
- `tests/expansion/test_generator.py` - test question-oriented prompt

### Integration Tests (Somnus)
```bash
# Before/after knowledge-update benchmark
cd ../somnus
uv run somnus bench run longmemeval --category knowledge-update --limit 20
```

### Manual Verification
```bash
# Seed test data
mcp__engrammic__remember("hoping to beat my personal best time of 25:50 in the charity 5K run")

# Query with asymmetric phrasing
mcp__engrammic__recall("What was my 5K time?")
# Expected: Should return the node with relevance > 0.7
```

### Regression Safety
- Run full Somnus benchmark suite to ensure no regression on other categories
- Compare recall@1 before/after for value-seeking questions

---

## Rollback Plan

Each phase is independently reversible:
- **Phase 1:** Set `hybrid_enabled: False` (instant rollback, no data loss)
- **Phase 3:** Revert prompt in `expansion/generator.py` (cached expansions will TTL out)
- **Phase 4:** Remove answer fragment logic from `query_expander.py`
- **Phase 5:** Remove temporal boost from `context.py:query()`

---

## Success Criteria

| Metric | Current | Target | Stretch |
|--------|---------|--------|---------|
| Knowledge-update accuracy | 29% | 55% | 65%+ |
| Recall@1 (value-seeking) | ~0.3 | 0.6 | 0.7+ |
| No regression on fact-recall | 90%+ | 90%+ | - |
| p95 query latency | <500ms | <600ms | - |

---

## Open Questions

1. **SPLADE model size:** `prithivida/Splade_PP_en_v1` is ~500MB. Verify it's acceptable for prod deployment or consider a distilled variant.

2. **Expansion model selection:** Which model is configured for `expansion_llm_model`? Flash-tier is fine for short generations, but verify cost/latency tradeoff.

3. **Hybrid mode recreation:** Need to decide policy for existing silos. Options:
   - Lazy recreation on first write after hybrid enabled
   - Admin CLI for explicit rebuild
   - Accept that old silos won't benefit until natural recreation

4. **Question generation cardinality:** Currently generates 3-5 questions. Should we increase to 5-7 for better coverage, or is this overkill?

---

## Appendix: Why Not HyDE?

HyDE (Hypothetical Document Embeddings) generates a fake answer at query time and embeds that instead. While effective, it:
- Adds significant query-time latency (LLM call per query)
- Requires careful prompt tuning to avoid hallucinated bias
- Cannot be cached effectively (queries are unique)

QuIM-RAG is superior here because:
- Index-time cost (amortized)
- Questions are more constrained than hypothetical answers
- Works with existing SPLADE/RRF infrastructure
