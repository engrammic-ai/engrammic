# Phase 7: CITE v2 Epistemology Implementation Plan

**Goal:** Add two-factor confidence (credibility + propagated), weighted evidence edges, damped propagation, PPR scoring, and consolidation subagent.

**Spec Reference:** `context/specs/cite-v2-epistemology.md`

---

## Progress Summary

**Completed (2026-06-01):**
- Core algorithms in `sage/epistemology.py`: propagation, PPR, corroboration weighting
- Schema: `SUPPORTS`/`CONTRADICTS` edges in primitives, propagation queries in `db/queries.py`
- Consolidation: `LLMResolver` with prompt template, MERGE/COEXIST/DEFER handling
- Recall: `ConfidenceBreakdown`, `conflict_status`, `has_unresolved_conflicts`
- Tests: 19 tests for epistemology algorithms

**Completed (2026-06-02):**
- Integration: Incremental propagation wired into `link` transaction for SUPPORTS/CONTRADICTS edges
- Caching: `PPRCache` with 5-min TTL in `sage/epistemology.py`
- Integration: PPR scoring integrated into recall pipeline (`_get_ppr_scores`)
- Integration: MERGE action creates merged claim + supersedes both nodes
- Tests: 5 tests for PPR cache (24 total epistemology tests)

**Remaining (Phase 7 scope):**
1. ~~**Integration**: Wire `compute_credibility` into `store_claim`~~ - was already done
2. ~~**Integration**: Wire incremental propagation into write-time transactions~~ - done 2026-06-02
3. ~~**Caching**: Add PPR cache with 5-min TTL (in-memory)~~ - done 2026-06-02
4. ~~**Integration**: Integrate PPR scores into recall scoring pipeline~~ - done 2026-06-02
5. ~~**Integration**: Wire MERGE action to create merged claim + supersede both~~ - done 2026-06-02
6. ~~**Tests**: Consolidation prompt parsing~~ - done 2026-06-02 (8 tests in TestLLMResolverParsing)
7. **Tests**: End-to-end integration tests (optional, requires live graph)

**Estimate:** Phase 7 core complete. E2E tests optional for further validation.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/sage/epistemology.py` | New: confidence propagation, PPR, corroboration weighting |
| `src/context_service/sage/consolidation.py` | Modify: add subagent interface and prompt |
| `src/context_service/sage/transactions.py` | Modify: add credibility computation to store_claim |
| `src/context_service/sage/recall.py` | Modify: integrate PPR scoring, confidence breakdown |
| `src/context_service/db/queries.py` | Add: edge weight queries, propagation helpers |
| `src/context_service/db/schema.py` | Add: SUPPORTS, CONTRADICTS edge types if missing |
| `tests/sage/test_epistemology.py` | New: propagation, PPR, corroboration tests |

---

## Task 1: Schema and Query Foundation

**Files:** `db/queries.py`, `db/schema.py`

- [x] Add `SUPPORTS` and `CONTRADICTS` to edge type enum if missing
- [x] Add queries:
  - `GET_SUPPORT_EDGES` - get weighted support edges for nodes
  - `GET_CONTRADICTION_EDGES` - get weighted contradiction edges
  - `GET_GRAPH_FOR_PROPAGATION` - batch fetch nodes + edges for matrix building
  - `CREATE_WEIGHTED_SUPPORT_EDGE` / `CREATE_WEIGHTED_CONTRADICTION_EDGE`
  - `UPDATE_PROPAGATED_CONFIDENCE` - batch update confidence scores
- [x] Verify schema supports `weight` property on edges

---

## Task 2: Credibility Computation (Static)

**Files:** `sage/transactions.py`, `sage/confidence.py`

Formula: `credibility = source_tier * method_weight * raw_confidence`

- [x] Add `SourceTier` enum: AUTHORITATIVE=1.0, VALIDATED=0.85, COMMUNITY=0.6, UNKNOWN=0.4
- [x] Add `MethodWeight` enum: VALIDATED=0.85, STANDARD=0.75, EXPERIMENTAL=0.6
- [x] Add `compute_credibility(source_tier, method_weight, raw_confidence) -> float`
- [x] Modify `store_claim` to accept `source_tier` and `method_weight`, compute and store credibility
- [x] Add `credibility` field to node properties (alongside existing `confidence`)

**Note:** Core computation done in `sage/confidence.py`; integration completed in store_claim.

---

## Task 3: Damped Confidence Propagation

**Files:** `sage/epistemology.py` (new)

Algorithm from spec Section 1.2:
```
x_new = clip((1 - alpha) * prior + alpha * (A+ - eta * A-) @ x, 0, 1)
```

- [x] Create `epistemology.py` with:
  - `build_adjacency_matrices(nodes, edges) -> (support_matrix, contradiction_matrix)`
  - `propagate_confidence(nodes, support, contradiction, alpha=0.8, eta=1.0) -> dict[node_id, float]`
- [x] Add depth-limited incremental propagation for write-time (depth 1-2 only)
- [x] Add full propagation for batch/groundskeeper

---

## Task 4: Independence-Weighted Corroboration

**Files:** `sage/epistemology.py`

Formula from spec Section 2.4:
```
source_weight = 1.0 + 0.5 * (sqrt(len(claims_from_source)) - 1)
total = sum(source_weights)
normalized = 1 - exp(-0.5 * total)
```

- [ ] Add `get_source_root(node) -> str` - trace to root source (agent + doc + evidence chain) - deferred
- [x] Add `compute_corroboration_weight(claim, corroborating_claims) -> float`
- [ ] Wire into `check_corroboration` helper in transactions.py - deferred

---

## Task 5: PPR-Based Transitive Scoring

**Files:** `sage/epistemology.py`, `sage/recall.py`

Algorithm from spec Section 3.1.

- [x] Add `personalized_pagerank(graph, query_nodes, alpha=0.85) -> dict[node_id, float]`
- [x] Add PPR cache with 5-minute TTL (in-memory) - `PPRCache` in epistemology.py
- [x] Integrate into recall:
  - Expand candidates via PPR from top-5 anchors
  - Multiply score by `ppr_scores.get(node_id, 0.1)`

---

## Task 6: Consolidation Subagent

**Files:** `sage/consolidation.py`

Prompt from spec Section 4.3.

- [x] Add `ConsolidationAction` enum: SUPERSEDE, MERGE, COEXIST, DEFER (in `ResolutionAction`)
- [x] Add `ConsolidationResult` dataclass with action, winner, rationale, merged_content (in `ResolutionResult`)
- [x] Add `consolidate_conflict(claim_a, claim_b, context, llm) -> ConsolidationResult` (in `LLMResolver`)
- [x] Add prompt template per spec (`CONSOLIDATION_PROMPT_TEMPLATE`)
- [x] Wire output handling:
  - SUPERSEDE: call `supersede(winner, loser, reason='resolves_contradiction')`
  - MERGE: create merged claim + supersede both original nodes
  - COEXIST: update conflict_status, reduce CONTRADICTS weight to 0.3
  - DEFER: leave unresolved, re-queue

---

## Task 7: Recall Integration

**Files:** `sage/recall.py`

- [x] Add `ConfidenceBreakdown` dataclass per spec Section 5.2
- [x] Modify `RecallResultItem` to include:
  - `conflict_status: str` (none, unresolved, resolved_*)
  - `confidence_breakdown: ConfidenceBreakdown`
- [x] Update scoring to use propagated confidence via PPR transitive scoring
- [x] Add `has_unresolved_conflicts` flag to `RecallResult`

---

## Task 8: Tests

**Files:** `tests/sage/test_epistemology.py`

- [x] Test `compute_credibility` with all tier/weight combinations (in test_confidence.py)
- [x] Test `propagate_confidence` converges correctly
- [x] Test contradiction edges reduce confidence
- [x] Test `compute_corroboration_weight` with independent vs same-source claims
- [x] Test `personalized_pagerank` produces expected scores
- [x] Test consolidation prompt parsing (8 tests in TestLLMResolverParsing)

---

## Dependencies

```
Task 1 (schema) 
    |
    +---> Task 2 (credibility) ---> Task 3 (propagation)
    |                                    |
    +---> Task 4 (corroboration) --------+---> Task 7 (recall integration)
    |                                    |
    +---> Task 5 (PPR) ------------------+
    |
    +---> Task 6 (consolidation) - can run in parallel

Task 8 (tests) - write alongside each task
```

---

## Performance Targets

| Operation | Target | Notes |
|-----------|--------|-------|
| Credibility computation | < 1ms | Simple formula, inline |
| Incremental propagation (depth 2) | < 50ms | Write-time, limited scope |
| Full propagation (1000 nodes) | < 2s | Batch only |
| PPR (cached) | < 10ms | Redis lookup |
| PPR (compute) | < 200ms | Included in recall budget |
| Consolidation | < 5s | LLM call, async |

---

## Out of Scope

- Semantic conflict detection (LLM-based, expensive) - deferred
- Agent track record scoring - needs usage data
- Human escalation UI - self-governing per spec
