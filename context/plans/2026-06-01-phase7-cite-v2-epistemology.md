# Phase 7: CITE v2 Epistemology Implementation Plan

**Goal:** Add two-factor confidence (credibility + propagated), weighted evidence edges, damped propagation, PPR scoring, and consolidation subagent.

**Spec Reference:** `context/specs/cite-v2-epistemology.md`

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

- [ ] Add `SUPPORTS` and `CONTRADICTS` to edge type enum if missing
- [ ] Add queries:
  - `GET_SUPPORT_EDGES` - get weighted support edges for nodes
  - `GET_CONTRADICTION_EDGES` - get weighted contradiction edges
  - `GET_GRAPH_FOR_PROPAGATION` - batch fetch nodes + edges for matrix building
  - `CREATE_WEIGHTED_EDGE` - create edge with weight property
- [ ] Verify schema supports `weight` property on edges

---

## Task 2: Credibility Computation (Static)

**Files:** `sage/transactions.py`, `sage/confidence.py`

Formula: `credibility = source_tier * method_weight * raw_confidence`

- [ ] Add `SourceTier` enum: AUTHORITATIVE=1.0, VALIDATED=0.85, COMMUNITY=0.6, UNKNOWN=0.4
- [ ] Add `MethodWeight` enum: VALIDATED=0.85, STANDARD=0.75, EXPERIMENTAL=0.6
- [ ] Add `compute_credibility(source_tier, method_weight, raw_confidence) -> float`
- [ ] Modify `store_claim` to accept `source_tier` and `method_weight`, compute and store credibility
- [ ] Add `credibility` field to node properties (alongside existing `confidence`)

---

## Task 3: Damped Confidence Propagation

**Files:** `sage/epistemology.py` (new)

Algorithm from spec Section 1.2:
```
x_new = clip((1 - alpha) * prior + alpha * (A+ - eta * A-) @ x, 0, 1)
```

- [ ] Create `epistemology.py` with:
  - `build_adjacency_matrices(nodes, edges) -> (support_matrix, contradiction_matrix)`
  - `propagate_confidence(nodes, support, contradiction, alpha=0.8, eta=1.0) -> dict[node_id, float]`
- [ ] Add depth-limited incremental propagation for write-time (depth 1-2 only)
- [ ] Add full propagation for batch/groundskeeper

---

## Task 4: Independence-Weighted Corroboration

**Files:** `sage/epistemology.py`

Formula from spec Section 2.4:
```
source_weight = 1.0 + 0.5 * (sqrt(len(claims_from_source)) - 1)
total = sum(source_weights)
normalized = 1 - exp(-0.5 * total)
```

- [ ] Add `get_source_root(node) -> str` - trace to root source (agent + doc + evidence chain)
- [ ] Add `compute_corroboration_weight(claim, corroborating_claims) -> float`
- [ ] Wire into `check_corroboration` helper in transactions.py

---

## Task 5: PPR-Based Transitive Scoring

**Files:** `sage/epistemology.py`, `sage/recall.py`

Algorithm from spec Section 3.1.

- [ ] Add `personalized_pagerank(graph, query_nodes, alpha=0.85) -> dict[node_id, float]`
- [ ] Add PPR cache with 5-minute TTL (Redis or in-memory)
- [ ] Integrate into recall:
  - Expand candidates via PPR from top-5 anchors
  - Multiply score by `ppr_scores.get(node_id, 0.1)`

---

## Task 6: Consolidation Subagent

**Files:** `sage/consolidation.py`

Prompt from spec Section 4.3.

- [ ] Add `ConsolidationAction` enum: SUPERSEDE, MERGE, COEXIST, DEFER
- [ ] Add `ConsolidationResult` dataclass with action, winner, rationale, merged_content
- [ ] Add `consolidate_conflict(claim_a, claim_b, context, llm) -> ConsolidationResult`
- [ ] Add prompt template per spec
- [ ] Wire output handling:
  - SUPERSEDE: call `supersede(winner, loser, reason='resolves_contradiction')`
  - MERGE: create new claim, supersede both
  - COEXIST: update conflict_status, reduce CONTRADICTS weight to 0.3
  - DEFER: leave unresolved, re-queue

---

## Task 7: Recall Integration

**Files:** `sage/recall.py`

- [ ] Add `ConfidenceBreakdown` dataclass per spec Section 5.2
- [ ] Modify `RecallResultItem` to include:
  - `conflict_status: str` (none, unresolved, resolved_*)
  - `confidence_breakdown: ConfidenceBreakdown`
- [ ] Update scoring to use propagated confidence, not raw
- [ ] Add `has_unresolved_conflicts` flag to `RecallResult`

---

## Task 8: Tests

**Files:** `tests/sage/test_epistemology.py`

- [ ] Test `compute_credibility` with all tier/weight combinations
- [ ] Test `propagate_confidence` converges correctly
- [ ] Test contradiction edges reduce confidence
- [ ] Test `compute_corroboration_weight` with independent vs same-source claims
- [ ] Test `personalized_pagerank` produces expected scores
- [ ] Test consolidation prompt parsing

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
