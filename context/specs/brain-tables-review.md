# Brain Tables Specification Review

**Status:** REVIEW  
**Date:** 2026-05-31  
**Reviewed by:** Claude (tables-first review)

---

## Executive Summary

The tables-first spec in `brain-transactions-overview.md` is a significant improvement over the initial transaction model. It addresses many concerns from the previous review (brain-transaction-review.md), particularly around missing transactions and the consistency model. However, gaps remain in cascade behavior, test scenario completeness, and some table inconsistencies.

**Overall assessment:** Ready for pseudocode with targeted fixes.

---

## 1. Completeness Check: EAG Transition Coverage

### Mapping EAG T1-T15 to Spec TX1-TX19

| EAG | Name | Spec TX | Status |
|-----|------|---------|--------|
| T1 | extract | TX1 | Covered |
| T2 | supersede | TX3 | Covered |
| T3 | synthesize | TX4 | Covered |
| T4 | revise | TX5 | Covered |
| T5 | consensus | TX6 | Covered |
| T6 | trace | TX7 | Covered |
| T7 | commit | TX8 | Covered |
| T8 | decay | TX9 | Covered (implicit) |
| T9 | hard-delete | TX10 | Covered |
| T10 | propose | TX11 | Covered (pending elimination) |
| T11 | accept | TX12 | Covered (pending elimination) |
| T12 | reject | TX13 | Covered (pending elimination) |
| T13 | crystallize | TX14 | Covered |
| T14 | forget | TX15 | Covered |
| T15 | cancel_forget | TX16 | Covered |

**All 15 EAG transitions are now covered.** This addresses the major gap from the previous review.

### Entity Types: Gaps

| Missing entity | Layer | Used by | Severity |
|---------------|-------|---------|----------|
| ProposedBelief | Wisdom | TX11-TX13 | LOW (pending elimination) |
| Agent | Meta | TX8, TX14 DECLARED_BY edge | MEDIUM |

**Issue:** INV7 requires a DECLARED_BY edge to "agent" but Agent is not in the entity table. Either:
1. Add Agent as an entity type, or
2. Clarify that agent_id is an attribute, not a node

### Transaction Gaps

| Missing TX | Description | Severity |
|------------|-------------|----------|
| STORE_MEMORY | Agent calls `remember` (Memory layer write) | HIGH |
| REFLECT | Agent calls `reflect` (Meta-Memory) | MEDIUM |
| HYPOTHESIZE | Agent creates WorkingHypothesis | MEDIUM |
| REVISE_HYPOTHESIS | Agent updates hypothesis before commit | LOW |

**Critical:** TX2 is STORE_CLAIM (Knowledge layer) but there's no equivalent for Memory layer writes via `remember`. The MCP tool `remember` needs a backing transaction.

---

## 2. Internal Consistency

### 2.1 State Diagram vs State Table Mismatch

**State table (Section 2):**
- TOMBSTONED transitions to: ACTIVE (cancel), DELETED

**State diagram:**
```
TOMBSTONED
    |    |
cancel   GC
    v    v
ACTIVE  DELETED
```

**Discrepancy:** The diagram shows GC (TX10) as the path to DELETED, which is correct. But the table says TOMBSTONED "Can transition to" DELETED, implying any mechanism. Clarify: only TX10 HARD_DELETE moves TOMBSTONED -> DELETED.

### 2.2 SUPERSEDED -> TOMBSTONED Path

**State diagram shows:** SUPERSEDED ---forget---> TOMBSTONED

**State table says:** SUPERSEDED transitions to TOMBSTONED

**Question:** Can you forget a superseded node? The diagram suggests yes, but this is philosophically odd. A superseded node is already "replaced." Forgetting it removes history. Is this intentional?

**Recommendation:** Document this explicitly. If allowed, explain the use case.

### 2.3 Transaction Table vs Reaction Table Mismatch

**TX18 PROMOTE:**
- Transaction table (Section 5): Listed as sync
- Reaction table (Section 9): "Corroboration threshold met -> Promote (TX18)" listed under "Immediate reactions (sync)"

This is consistent.

**TX19 DEMOTE:**
- Transaction table (Section 5): Not listed (missing from TX table!)
- Section 7 (Sync boundary): TX19 mentioned as "Can be Either"
- Reaction table: No DEMOTE reaction listed

**Bug:** TX19 exists in some tables but not others. The transaction table stops at TX18 but Section 7 references TX19.

**Fix:** Add TX19 DEMOTE to Section 5's transaction table:
```
| TX19 | DEMOTE | - | Evidence withdrawn | Fact -> Claim | Sync |
```

And add to Section 6:
```
| TX19 DEMOTE | fact_id | updated claim | No | - |
```

### 2.4 Invariant vs Transaction Alignment

| Invariant | Enforced by (per table) | Actually enforced by |
|-----------|-------------------------|---------------------|
| INV2 | TX2, TX18 | Also TX1 (extraction creates DERIVED_FROM) |
| INV3 | TX4 | Also TX5 (revise must maintain edge count) |
| INV7 | TX8, TX14 | What about TX6 CONSENSUS creating Facts? |

**Gap:** INV2 says "Every Fact has >= 1 DERIVED_FROM to Memory." TX6 CONSENSUS creates Facts from ReasoningChains. Does this satisfy INV2? ReasoningChain is Intelligence layer, not Memory.

**Recommendation:** Either:
1. ReasoningChain counts as "Memory-equivalent" for INV2, or
2. TX6 must trace through to underlying Memory nodes, or
3. Clarify that consensus-promoted Facts have different provenance rules

---

## 3. Missing Columns/Rows

### Section 1: Entity Types

| Missing column | Purpose |
|----------------|---------|
| Primary key | What uniquely identifies each entity? (node_id assumed) |
| Required edges | What edges must exist? (e.g., Fact requires DERIVED_FROM) |
| Created by TX | Which transaction(s) create this entity? |
| Layer transitions | What other layers can this entity transition to? |

**Missing row:** Agent (referenced by INV7)

### Section 5: Transactions

| Missing column | Purpose |
|----------------|---------|
| Preconditions | What must be true before TX can run? |
| Postconditions | What is guaranteed after TX completes? |
| Edges created | What provenance edges are written? |
| Idempotent? | Can TX be safely retried? |
| Compensation TX | If TX fails mid-way, how to roll back? |

### Section 6: Transaction Detail

| Missing column | Purpose |
|----------------|---------|
| Lock scope | What is locked during TX? (for race condition prevention) |
| Timeout | Max execution time before abort |
| Retry policy | Exponential backoff? Max attempts? |

### Section 8: Invariants

| Missing column | Purpose |
|----------------|---------|
| Violation recovery | If invariant found violated, how to repair? |
| Monitoring | How to detect violations? |

### Section 9: Reactions

| Missing information | Purpose |
|---------------------|---------|
| Debounce rules | Multiple rapid events -> single reaction? |
| Rate limits | Max reactions per second/minute |
| Priority relative to transactions | Does TX3 supersede a pending synthesis? |

---

## 4. Ambiguities

### 4.1 TX3 SUPERSEDE Triggers

Section 5 says: "Trigger: Conflict detected OR agent revises"

Questions:
1. What constitutes "conflict detected"? Same (s,p,o) with different value? Semantic conflict?
2. How does "agent revises" differ from "agent calls learn with supersedes parameter"?
3. Is TX3 ever called implicitly, or only through TX2?

### 4.2 TX4 SYNTHESIZE "Query-time" Mode

Section 5: "Async (or sync on query)"
Section 7: "TX4 SYNTHESIZE (on query) - Sync = latency hit; Async = stale results"

Questions:
1. How does the system decide sync vs async on query?
2. What's the timeout for sync synthesis?
3. If synthesis times out, does query return partial results or error?

### 4.3 Cluster Definition

TX4/TX7/TX11 reference "cluster_id" but clusters are never defined.

Questions:
1. What is a cluster? Embedding similarity? Graph connectivity?
2. How are clusters computed? Async job? Query-time?
3. Can a node belong to multiple clusters?
4. What happens when cluster membership changes?

### 4.4 "Hot Passage" Definition

TX1 trigger: "Document ingested or hot passage"

Questions:
1. What makes a passage "hot"?
2. Is this heat-based threshold? Query frequency?
3. How does hot passage differ from document ingestion trigger?

### 4.5 TX9 DECAY "Implicit"

Section 5: "Implicit" for Sync/Async
Section 6: "(implicit)" for inputs

Questions:
1. Is decay computed at query time or stored?
2. Does decay ever trigger state changes, or just weight adjustments?
3. What's the decay function? Time-based? Access-based?

### 4.6 TX8 vs TX14: COMMIT vs CRYSTALLIZE

Both create Commitments. The difference:
- TX8 COMMIT: "Agent declares stance"
- TX14 CRYSTALLIZE: "Agent crystallizes hypothesis"

Questions:
1. Can COMMIT be used without a prior hypothesis?
2. Is CRYSTALLIZE the only way to turn WorkingHypothesis into Commitment?
3. What happens to the WorkingHypothesis after CRYSTALLIZE?

---

## 5. Decision Point Critique (Section 12)

### 5.1 ProposedBelief flow (TX11-13)?

**Options:** Keep / Eliminate  
**Recommendation:** Eliminate

**Tradeoffs:**

| Keep | Eliminate |
|------|-----------|
| Human-in-loop validation | Simpler model |
| Quality gate for weak synthesis | Fewer states to track |
| Matches EAG theory | Matches brain-architecture.md intent |
| More complexity | Confidence threshold handles weak cases |

**My recommendation:** Eliminate, but with mitigation:
1. Add confidence_threshold to TX4. Below threshold -> don't create Belief at all
2. Log "synthesis skipped (low confidence)" for monitoring
3. Re-trigger synthesis when cluster gains more evidence

**Rationale:** ProposedBelief adds state machine complexity for a rare case. The current MCP surface has no `propose`/`accept`/`reject` verbs, suggesting this was already de-prioritized.

### 5.2 Lazy synthesis on query?

**Options:** Yes / No  
**Recommendation:** Yes, with timeout

**Tradeoffs:**

| Eager-only | Lazy on query |
|------------|---------------|
| Predictable latency | First-query latency spike |
| Wasted work on unused clusters | Only synthesize what's needed |
| Synthesis always current | May timeout on large clusters |

**My recommendation:** Yes with 2s timeout, fallback to facts-only response with "synthesis_pending" marker.

**Additional concern:** Need deduplication. Multiple concurrent queries for same cluster should share synthesis, not duplicate.

### 5.3 Cascade depth limit?

**Options:** N = ?  
**Recommendation:** 10

**Analysis:** 10 seems reasonable for most graphs. However:
- Need telemetry to validate this choice
- Consider adaptive limit based on graph size
- Log when limit is hit so it can be tuned

**Concern:** Is depth the right metric? A depth-3 cascade touching 10,000 nodes is worse than depth-15 touching 30 nodes. Consider node count limit as well.

### 5.4 Idle-time threshold?

**Options:** N seconds  
**Recommendation:** 60s per silo

**Missing context:** What happens at idle? The term "dreaming" is used but not defined. Is this:
- Cleanup of stale synthesis?
- Proactive synthesis of hot clusters?
- Garbage collection?

**Recommendation:** Define idle-time behavior before picking threshold.

### 5.5 Conflict tiebreaker?

**Options:** Timestamp / LLM / Reject both  
**Recommendation:** Timestamp (older wins)

**Tradeoffs:**

| Timestamp (older) | Timestamp (newer) | LLM | Reject both |
|-------------------|-------------------|-----|-------------|
| Stable (first wins) | Fresh (latest wins) | Semantic quality | No data loss |
| May keep outdated | Churn on rapid updates | Expensive, slow | Both stay as conflict |
| Predictable | Predictable | Unpredictable | Requires resolution |

**My recommendation:** Timestamp (older wins) for structural conflicts, with option to escalate semantic conflicts to LLM asynchronously.

**Concern with "older wins":** If an agent corrects a mistake, the correction (newer) loses. Consider: if same agent, newer wins. If different agents, older wins.

### 5.6 Demote on evidence withdrawal?

**Options:** Yes / No  
**Recommendation:** Yes

**Rationale:** A Fact without corroboration is just a Claim. Demotion maintains semantic integrity.

**Edge case:** What if Fact is SYNTHESIZED_FROM for a Belief? Demotion might cascade to Belief invalidation. Document this.

### 5.7 Cancel window duration?

**Options:** N minutes  
**Recommendation:** 60 min

**Tradeoffs:**

| Short (15 min) | Medium (60 min) | Long (24 hr) |
|----------------|-----------------|--------------|
| Quick cleanup | Reasonable undo window | Extended recovery |
| Less storage | Moderate storage | More storage |
| Harder recovery | Balance | Easier recovery |

**Recommendation:** 60 min is reasonable for interactive sessions. Consider making this configurable per-silo for enterprise users who want longer retention.

---

## 6. Test Scenario Gaps (Section 13)

### Missing Scenarios

| Scenario | Why needed |
|----------|------------|
| Agent stores claim, immediately recalls it | Read-your-writes consistency |
| Synthesis completes during active recall | Race condition |
| Two concurrent synthesis jobs for same cluster | Deduplication |
| Claim stored with evidence URL that times out | Network failure handling |
| Node at max cascade depth, further changes | Depth limit behavior |
| WorkingHypothesis expires mid-session | Session cleanup |
| Agent commits hypothesis, session ends before persistence | Durability |
| GDPR deletion request for node with dependents | Cascade delete |
| Restore tombstoned node that was superseder | Loser revival question |
| Query with as_of timestamp during cascade | Temporal consistency |
| High cardinality cluster (10k facts) synthesis | Resource limits |
| Zero-fact cluster synthesis attempt | Edge case |
| Circular evidence (A cites B, B cites A) | Cycle handling |
| Belief based on single Fact (below N threshold) | INV3 enforcement |

### Scenarios with Missing Outcomes

All scenarios in Section 13 say "outcomes TBD." Each needs:

1. **Two agents write same (s,p,o) simultaneously**
   - Outcome: Second writer gets CONFLICT_DETECTED error with winner_id
   - Or: Second writer's claim auto-supersedes first (race condition concern)

2. **Query during active synthesis**
   - Outcome: Return facts + `synthesis_status: "in_progress"` + `estimated_completion_ms: N`

3. **Evidence URL 404**
   - Outcome: Which of these?
     - Reject write entirely (strict)
     - Store with `evidence_status: "unverified"` and degraded confidence
     - Store but mark for re-verification

### Missing Edge Cases

| Category | Missing case |
|----------|--------------|
| Memory layer | remember without any tags |
| Memory layer | remember duplicate content |
| Knowledge layer | learn without evidence (should reject per INV2) |
| Knowledge layer | learn with file:// evidence (current policy: reject) |
| Wisdom layer | believe without about_refs |
| Intelligence layer | hypothesize in non-existent session |
| Cross-layer | belief about a tombstoned fact |
| Cross-layer | link between nodes in different states |

---

## 7. Sync/Async Boundary Critique (Section 7)

### Correctly Classified

| TX | Classification | Assessment |
|----|----------------|------------|
| TX2 STORE_CLAIM | Sync | Correct (caller needs node_id) |
| TX8 COMMIT | Sync | Correct (agent expects persistence) |
| TX15 FORGET | Sync | Correct (agent expects effect) |
| TX1 EXTRACT | Async | Correct (LLM, expensive) |
| TX4 SYNTHESIZE | Async | Correct (LLM, expensive) |
| TX10 HARD_DELETE | Async | Correct (scheduled GC) |

### Questionable Classifications

| TX | Current | Concern |
|----|---------|---------|
| TX3 SUPERSEDE | Sync | If supersession triggers deep cascade, sync may timeout |
| TX17 LINK | Sync | Depends on validation complexity. Cross-silo check is O(1), but cycle detection for certain edge types could be O(n) |
| TX18 PROMOTE | Sync | Part of write-time reaction chain is correct, but what if promotion triggers synthesis trigger check? |

### Missing from Classification

TX19 DEMOTE is mentioned in "Can be Either" but not in the main tables.

### Hybrid Recommendation

For TX3 SUPERSEDE:
- Sync: Create supersedes edge, update node state
- Async: Cascade staleness propagation

This matches Section 10's "Depth 1 sync, rest async" but should be explicit in Section 7.

---

## 8. Cascade Risks (Section 10)

### Compared to Previous Review Concerns

| Previous review concern | Section 10 coverage |
|-------------------------|---------------------|
| Staleness cascade storm | Yes: depth limit, async after depth 1 |
| Infinite synthesis loop | Partially: need to verify Belief doesn't re-trigger its cluster |
| Cascade depth limit | Yes: 10 (configurable) |
| Diamond dependency | Not addressed |
| Cascade atomicity | Not addressed |

### Remaining Gaps

**Diamond dependency:**
```
A -> B
A -> C
B -> D
C -> D
```
If A changes, D is marked stale via B, then again via C. Section 10 doesn't address:
1. Deduplication (mark stale once, not twice)
2. Ordering (B path vs C path might have different effects)

**Cascade atomicity:**
If cascade is interrupted (service crash, timeout), what state is the graph in?
- Partially stale beliefs?
- Missing staleness markers?

**Recommendation:** Add a cascade_id to track cascades. If cascade is interrupted, resume from last known state.

**Heat propagation:**
Section 10 mentions PPR diffusion for heat but doesn't specify:
1. Damping factor
2. Max iterations
3. Convergence threshold

### Missing Cascade Type

| Cascade | Trigger | Not in Section 10 |
|---------|---------|-------------------|
| Tombstone cascade | Node tombstoned | Listed ("Cascade to dependents") |
| Supersession cascade | Node superseded | Listed |
| Evidence removal cascade | Edge removed | Listed |
| **Restoration cascade** | **Node restored (cancel forget)** | **Missing** |

When a tombstoned node is restored, what happens to:
- Nodes that were cascade-tombstoned because of it?
- Staleness markers set because of it?

---

## 9. Practical Implementation Concerns

### Hard to Implement

| Aspect | Difficulty | Why |
|--------|-----------|-----|
| Cluster computation | High | No definition provided. Embedding similarity requires periodic recomputation. Graph connectivity requires efficient traversal. |
| Semantic conflict detection | High | Structural (s,p,o) matching is insufficient. "Python 3.12 requires X" vs "Python 3.13 doesn't require X" are semantically related but structurally different. |
| Query-time synthesis with timeout | Medium | Need to track in-progress synthesis, handle timeout gracefully, deduplicate concurrent requests. |
| Cascade depth limiting | Medium | BFS/DFS with depth tracking is straightforward, but detecting when to async-offload requires careful state management. |
| Cancel window enforcement | Low-Medium | Timer-based, but distributed timers are tricky. Clock skew across nodes? |

### Underspecified for Implementation

| Component | What's missing |
|-----------|---------------|
| Event queue | Partitioning scheme, ordering guarantees, failure handling, dead letter queue |
| Lock strategy | Pessimistic vs optimistic, lock granularity, deadlock prevention |
| LLM integration | Model selection, prompt templates, fallback behavior, cost controls |
| Cluster algorithm | Distance metric, threshold, incremental vs batch update |
| Heat/freshness/priority | Formulas, update frequency, query-time vs materialized |
| Session management | How WorkingHypothesis ties to session, session timeout, cleanup |

### Resource Limits Not Specified

| Resource | Need limit? |
|----------|-------------|
| Max claims per silo | Yes (storage) |
| Max edges per node | Maybe (query performance) |
| Max cluster size | Yes (synthesis cost) |
| Max cascade depth | Yes (10, per spec) |
| Max concurrent synthesis | Yes (LLM cost) |
| Max evidence URLs per claim | Yes (validation cost) |

---

## 10. Comparison to Previous Review

### Must Fix Items from brain-transaction-review.md

| Item | Previous review | Tables spec status |
|------|-----------------|-------------------|
| Add T_FORGET, T_CANCEL_FORGET, T_HARD_DELETE | Missing | **FIXED** (TX15, TX16, TX10) |
| Add T_COMMIT, T_CRYSTALLIZE | Missing | **FIXED** (TX8, TX14) |
| Define consistency model | Missing | **FIXED** (Section 11) |
| Add race condition handling to T1 | Missing | **PARTIAL** - mentioned in test scenarios but no lock strategy defined |
| Define cascade depth limits | Missing | **FIXED** (Section 10, default 10) |
| Specify T9 behavior: inline vs async for deep cascades | Missing | **FIXED** (Section 10: "Depth 1 sync, rest async") |

### Should Fix Items

| Item | Previous review | Tables spec status |
|------|-----------------|-------------------|
| Add T_LINK | Missing | **FIXED** (TX17) |
| Add T_DECAY or document implicit | Missing | **FIXED** (TX9, implicit) |
| Define superseding node tombstoned behavior | Missing | **PARTIAL** - test scenario exists but outcome TBD |
| Clarify T8 completion handling | Missing | **NOT ADDRESSED** - async completion still unclear |
| Document ProposedBelief elimination as intentional | Missing | **FIXED** (Section 5 note, Section 12 decision) |

### New Issues Introduced

| Issue | Severity |
|-------|----------|
| TX19 DEMOTE inconsistently present | Medium |
| STORE_MEMORY transaction missing | High |
| Agent entity type missing | Medium |
| Cluster definition missing | High |
| T8/T14 distinction unclear | Medium |

---

## 11. Recommendations Summary

### Must Fix Before Pseudocode

1. **Add TX0 STORE_MEMORY** - The `remember` MCP tool needs a backing transaction
2. **Fix TX19 DEMOTE** - Add to Section 5 and Section 6 tables
3. **Define clusters** - Add Section X: Cluster Computation
4. **Define lock strategy** - Add to Section 6 (lock scope column)
5. **Complete test scenario outcomes** - Every scenario needs expected behavior
6. **Address restoration cascade** - What happens when cancel_forget succeeds?

### Should Fix

1. Add Agent to entity table (or clarify agent_id is attribute)
2. Clarify TX8 COMMIT vs TX14 CRYSTALLIZE distinction
3. Define idle-time behavior (what is "dreaming"?)
4. Add cascade deduplication (diamond dependency)
5. Define async completion handling for TX4/TX5/TX11

### Document Explicitly

1. Can you forget a superseded node? (State diagram shows yes)
2. INV2 applicability to consensus-promoted Facts
3. What happens to WorkingHypothesis after CRYSTALLIZE?
4. Evidence validation policy (file:// rejected, 404 handling)

---

## 12. Appendix: Suggested Table Additions

### A. TX0 STORE_MEMORY

For Section 5:
```
| TX0 | STORE_MEMORY | - | Agent calls `remember` | -> Memory | Sync |
```

For Section 6:
```
| TX0 STORE_MEMORY | content, tags?, silo_id | node_id | Yes (invariant) | Reject write |
```

### B. TX19 DEMOTE (Fix)

For Section 5:
```
| TX19 | DEMOTE | - | Evidence withdrawn | Fact -> Claim | Sync |
```

For Section 6:
```
| TX19 DEMOTE | fact_id | updated claim | No | - |
```

### C. Entity Table Additions

```
| Agent | Meta | System or user agent | No | No |
```

### D. Cluster Definition (New Section)

Suggested addition between Sections 4 and 5:

```
## 4.5 Cluster Definition

A cluster is a set of Facts that are candidates for synthesis into a Belief.

| Property | Value |
|----------|-------|
| Membership | Facts within embedding distance D of centroid |
| Minimum size | N facts (same as INV3 threshold) |
| Maximum size | Configurable (default 1000) |
| Recomputation | Incremental on fact creation, periodic batch |
| Overlap | A fact may belong to multiple clusters |

| Cluster state | Meaning |
|---------------|---------|
| PENDING | Below density threshold |
| READY | Density threshold met, awaiting synthesis |
| SYNTHESIZED | Has active Belief |
| STALE | Source facts changed since synthesis |
```

---

## Conclusion

The tables-first spec successfully addresses the major gaps from the previous review. The architecture is now complete enough that pseudocode can be written for most transactions. The main blockers are:

1. Missing STORE_MEMORY transaction (breaks `remember`)
2. Undefined cluster computation (breaks TX4/TX7/TX11)
3. Incomplete test scenario outcomes (blocks implementation validation)

Once these are addressed, the spec is ready for pseudocode expansion.
