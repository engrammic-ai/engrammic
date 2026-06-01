# Brain Transaction Model Review

**Status:** REVIEW  
**Date:** 2026-05-31

This document reviews the transaction model primitives (T1-T10, INV1-6) against the brain architecture draft and EAG theory (03-transitions.md).

---

## 1. Missing Transactions

The proposed model has 10 transactions. EAG theory defines 15 transitions. The following are absent or underspecified:

### 1.1 FORGET (T14 in EAG)

**Severity: HIGH**

The model has `TOMBSTONED` and `DELETED` states but no transaction to reach them. Agent-initiated deletion is a core EAG operation.

Missing:
- T_FORGET: Mark node as tombstoned, start cancel window
- T_CANCEL_FORGET: Restore node within cancel window (T15 in EAG)
- T_HARD_DELETE: Scheduled GC that moves TOMBSTONED -> DELETED

Without these, there's no way to implement the `forget` MCP tool or GDPR erasure.

### 1.2 LINK

**Severity: MEDIUM**

The model assumes edges are created implicitly (DERIVED_FROM on store, SUPERSEDES on conflict). But agents explicitly create typed relationships via the `link` tool. Missing:

- T_LINK: Create arbitrary typed edge between nodes
- Needs: cross-silo validation (INV5), cycle detection for certain edge types

### 1.3 UPDATE / REVISE

**Severity: HIGH**

T4 (SUPERSEDE) handles losers in conflict resolution. But what about:
- Agent-initiated revision (correcting their own claim)?
- Wisdom -> Wisdom revision on evidence shift (T4 in EAG)?

The model conflates "loser in conflict" with "general supersession." These are different:
- Conflict resolution: system picks winner
- Revision: agent updates their own prior claim
- Evidence shift: automated re-synthesis

### 1.4 DECAY (T8 in EAG)

**Severity: MEDIUM**

EAG specifies Memory decay (retrieval weight -> 0). The model has no transaction for this. Is decay an implicit query-time computation or an explicit state change?

### 1.5 COMMIT / CRYSTALLIZE (T7, T13 in EAG)

**Severity: HIGH**

EAG has two paths to Wisdom:
1. System synthesis: Facts -> Belief (covered by T8 SYNTHESIZE)
2. Agent commitment: WorkingHypothesis -> Commitment (missing)

The `commit` and `crystallize` MCP tools need a transaction. This is agent-authored Wisdom, distinct from system-synthesized Wisdom.

### 1.6 EXTRACT (T1 in EAG)

**Severity: MEDIUM**

EAG T1 is Memory -> Knowledge extraction. The transaction model's T1 is STORE_CLAIM which receives already-extracted claims. Document this boundary explicitly.

### 1.7 CONSENSUS (T5 in EAG) and TRACE (T6 in EAG)

**Severity: LOW**

Multi-agent consensus and reasoning chain linkage. Likely deferred, but note their absence.

---

## 2. Edge Cases Per Transaction

### T1: STORE_CLAIM

| Scenario | Gap |
|----------|-----|
| Evidence URL returns 404 | Does write fail? Soft-fail with warning? |
| Evidence URL requires auth | Validation can't verify content |
| Two agents store same claim simultaneously | Race to trigger T2? Both trigger? |
| Referenced node doesn't exist | Reject? Or create dangling edge? |
| Claim references TOMBSTONED node | Should this be allowed? |
| Circular DERIVED_FROM attempted | No cycle detection specified |

**Race condition detail:** Agent A and Agent B both call `learn("X is true")` at t=0. Both pass the "no conflict exists" check. Both write. Now INV1 is violated. Need: optimistic locking, or serialization on (silo, subject, predicate).

### T2: CHECK_CONSISTENCY

| Scenario | Gap |
|----------|-----|
| Three-way conflict (A, B, C all contradict) | Pairwise resolution order matters |
| Semantic contradiction vs structural | Model says "structural," but subject/predicate matching is brittle |
| Conflict with SUPERSEDED node | Should superseded nodes be invisible to conflict check? |

**Semantic gap:** Two claims: "Python 3.12 requires X" and "Python 3.13 doesn't require X." Same subject? Same predicate? Structural matching won't catch this.

### T3: RESOLVE_CONFLICT

| Scenario | Gap |
|----------|-----|
| Tie score | Who wins? Random? Timestamp? Reject both? |
| Winner later found to be wrong | No mechanism to re-evaluate |
| Resolution changes after T5 runs | Corroboration invalidated? |

### T4: SUPERSEDE

| Scenario | Gap |
|----------|-----|
| Supersession during active synthesis | SYNTHESIZE may reference about-to-be-superseded node |
| Double supersession | A supersedes B, then C supersedes A. Is B doubly-superseded? |
| Superseding a TOMBSTONED node | Should be disallowed but not specified |
| Cascade depth limit | A -> B -> C -> D -> ... How deep before abort? |

### T5: CHECK_CORROBORATION

| Scenario | Gap |
|----------|-----|
| Corroboration from same source | Two claims from same document shouldn't count as independent |
| Corroboration from SUPERSEDED claims | Do these count? |
| Corroboration count decremented | What happens when corroborating claim is tombstoned? |

### T6: PROMOTE_TO_FACT

| Scenario | Gap |
|----------|-----|
| Promoted during active conflict resolution | State machine collision |
| Promotion threshold met by noise | Low-quality corroboration flooding |

### T7: CHECK_SYNTHESIS_TRIGGER

| Scenario | Gap |
|----------|-----|
| Cluster definition | What IS a cluster? Embedding similarity? Graph locality? |
| Overlapping clusters | Fact belongs to multiple clusters. Synthesize all? |
| Synthesis already in progress | Re-triggering creates duplicates |

### T8: SYNTHESIZE

| Scenario | Gap |
|----------|-----|
| LLM times out | Retry? Abandon? Mark cluster as "synthesis failed"? |
| LLM returns low-confidence result | Store anyway? Discard? |
| Facts change during synthesis | Synthesized belief immediately stale |
| LLM hallucinates beyond input facts | Belief contains claims not in SYNTHESIZED_FROM edges |

**Critical gap:** T8 is async but there's no transaction for handling async completion. What happens when synthesis finishes?

### T9: CASCADE_STALENESS

| Scenario | Gap |
|----------|-----|
| Diamond dependency | A -> B, A -> C, B -> D, C -> D. D marked stale twice? |
| Cascade touches hot cluster | Triggers synthesis which triggers more cascades |
| Maximum cascade depth | Infinite loop if cycles exist (INV4 should prevent, but...) |

### T10: RECALL

| Scenario | Gap |
|----------|-----|
| Lazy synthesis latency | First query pays 2s+ penalty |
| Multiple concurrent queries for same unsynthesized cluster | All trigger synthesis? |
| Query during active cascade | Stale data returned? Block until cascade completes? |

---

## 3. Invariant Violations

### INV1: No two ACTIVE claims with same (silo, subject, predicate) and different object

**How violated:**
1. Race condition in T1 (two writes pass check before either commits)
2. Subject/predicate canonicalization failure
3. Restoration from backup doesn't re-run consistency checks

**Prevention needed:**
- Pessimistic lock on (silo, subject, predicate) during T1
- Or optimistic lock with retry on conflict
- Post-write invariant assertion

### INV2: Every ACTIVE Fact has >= 1 DERIVED_FROM edge to Memory layer

**How violated:**
1. Direct fact insertion bypassing T1
2. Edge deletion without cascading to node
3. Memory node tombstoned but fact remains ACTIVE

**Prevention needed:**
- T1 rejects writes without valid DERIVED_FROM target
- Cascade: Memory tombstone -> derived Facts become... what?

### INV3: Every ACTIVE Belief has >= N SYNTHESIZED_FROM edges to ACTIVE Facts

**How violated:**
1. Facts superseded after Belief created
2. N changes (config update) and existing Beliefs no longer meet threshold
3. Facts tombstoned, Belief not invalidated

**Prevention needed:**
- Belief validation on creation
- Cascade: Fact state change -> count Belief's remaining edges, invalidate if < N

### INV4: SUPERSEDES edges never form cycles

**How violated:**
1. T4 doesn't check for cycles before creating edge
2. Concurrent supersessions: A supersedes B while B supersedes A

**Prevention needed:**
- DFS cycle check before creating SUPERSEDES edge
- Or: enforce SUPERSEDES as append-only linked list (newer always points to older)

### INV5: All nodes in silo's graph belong to that silo

**How violated:**
1. Cross-silo LINK
2. DERIVED_FROM or SYNTHESIZED_FROM crosses silos

**Prevention needed:**
- Every edge-creating transaction validates source.silo_id == target.silo_id

### INV6: Tombstoned nodes invisible to RECALL

**How violated:**
1. Query races with T_FORGET
2. Cached query results include tombstoned node
3. Graph traversal follows edge to tombstoned node

**Prevention needed:**
- RECALL query includes `WHERE NOT tombstoned` predicate
- Cache invalidation on tombstone

---

## 4. Consistency Model Gaps

The model does not declare its consistency level. This is a critical omission.

**Unanswered Questions:**

1. **Read-your-writes:** After T1 completes, does immediate T10 see the new claim?
2. **Causal consistency:** Agent A writes, tells Agent B. Does Agent B see A's write?
3. **Synthesis visibility:** T8 is async. When does RECALL see the new Belief?
4. **Cascade atomicity:** Is T9 atomic? Can RECALL observe partial staleness?
5. **Conflict window:** T1-T3 inline, but is there a window where INV1 is violated?

**Recommendation:** State explicitly: "Writes are strongly consistent within a silo," "Synthesis is eventually consistent," "Cross-agent ordering is not guaranteed."

---

## 5. Cascade Risks

### 5.1 Staleness Cascade Storm

**Scenario:** Core fact F is SYNTHESIZED_FROM for 100 Beliefs. F is superseded.

T4(F) triggers T9, cascading to B1...B100. Each Bi marked stale. 100 synthesis triggers queued. Hot cluster detection fires. More synthesis triggers.

**Mitigation needed:**
- Rate limiting on synthesis triggers
- Debounce: don't synthesize if another trigger for same cluster is pending
- Priority cap: cascade-induced synthesis is lower priority than direct query

### 5.2 Infinite Synthesis Loop

**Scenario:** Cluster C ready for synthesis. T8 creates Belief B. B is itself a node; does B joining C trigger new synthesis? Loop.

**Prevention:** Beliefs should not trigger synthesis of the cluster they belong to.

### 5.3 Cascade Depth Limit

No transaction specifies a maximum cascade depth. Pathological graphs could cause stack overflow, memory exhaustion, or timeout.

**Recommendation:** Hard limit (e.g., depth 10), log warning, fail open.

---

## 6. Async Boundary Critique

**T9 CASCADE_STALENESS is inline but unbounded.**

If cascade touches 1000 nodes, the inline write operation takes O(1000). This violates the "< 50ms added latency" target.

**Recommendation:** T9 should be inline for immediate dependents (depth 1), async for deeper cascade.

**T10 RECALL with lazy synthesis crosses async boundary.**

RECALL is sync, but triggers async T8 if synthesis needed. How does caller know when synthesis is done?

Options:
1. Block RECALL until synthesis completes (violates latency target)
2. Return partial results with "synthesis in progress" marker
3. Return facts only, suggest re-query later

Current model unclear on this.

**Missing: What transaction handles async completion?**

When T8 finishes, where is Belief stored? How is cache updated? How are waiting queries notified? Need T_SYNTHESIS_COMPLETE or make T8's storage explicit.

---

## 7. Missing State Transitions

### Node State Machine (Current)

```
[creation] -> ACTIVE
ACTIVE -> SUPERSEDED (T4)
ACTIVE -> TOMBSTONED (???)
TOMBSTONED -> DELETED (???)
```

### Missing Transitions

- ACTIVE -> TOMBSTONED via T_FORGET
- TOMBSTONED -> ACTIVE via T_CANCEL_FORGET
- TOMBSTONED -> DELETED via T_HARD_DELETE
- SUPERSEDED -> TOMBSTONED: Can you forget a superseded node?
- SUPERSEDED -> ACTIVE: If superseding node is tombstoned, does loser revive?

**Edge case:** A supersedes B. A is tombstoned. Is B now the active version? Or does B stay superseded? Semantically important and not specified.

### Claim Lifecycle Gaps

- PROMOTED -> UNPROMOTED (demotion on evidence withdrawal)?
- UNPROMOTED -> INVALIDATED (claim disproven)?

### Belief Lifecycle Gaps

- FRESH -> INVALIDATED (all source facts tombstoned)?
- STALE -> INVALIDATED (re-synthesis fails)?
- Any state -> TOMBSTONED (agent forgets belief)?

---

## 8. Comparison to EAG Theory (03-transitions.md)

### Transition Coverage

| EAG Transition | Model Coverage |
|---------------|----------------|
| T1 Memory -> Knowledge (extract) | NOT COVERED (boundary) |
| T2 Knowledge -> Knowledge (supersede) | T3 + T4 covers |
| T3 Knowledge -> Wisdom (synthesize) | T8 covers |
| T4 Wisdom -> Wisdom (revise) | PARTIAL (T9 marks stale) |
| T5 Intelligence -> Knowledge (consensus) | NOT COVERED |
| T6 Intelligence -> Memory (trace) | NOT COVERED |
| T7 Intelligence -> Wisdom (commit) | NOT COVERED |
| T8 Memory -> null (decay) | NOT COVERED |
| T9 Memory -> null (hard-delete) | NOT COVERED |
| T10-T12 ProposedBelief flow | NOT COVERED (intentionally eliminated) |
| T13 Intelligence -> Wisdom (crystallize) | NOT COVERED |
| T14 Any -> tombstone (forget) | NOT COVERED |
| T15 tombstone -> restored (cancel) | NOT COVERED |

**Summary: 5/15 EAG transitions have model coverage**

### Critical Misalignment: Agent Commitment Path

EAG T7 (commit) and T13 (crystallize) are the agent-authored path to Wisdom. The brain transaction model only covers system-synthesized Wisdom (T8 SYNTHESIZE).

This means:
- `commit` MCP tool has no transaction backing
- `hypothesize` workflow cannot crystallize
- Agent beliefs cannot be stored

**This must be fixed. Add T_COMMIT and T_CRYSTALLIZE transactions.**

### ProposedBelief Elimination

brain-architecture.md explicitly removes ProposedBelief. This is a valid architectural decision but should be documented as intentional divergence from EAG theory, not an oversight.

---

## 9. Summary of Required Changes

### Must Fix (Blocking)

1. Add T_FORGET, T_CANCEL_FORGET, T_HARD_DELETE transactions
2. Add T_COMMIT, T_CRYSTALLIZE transactions for agent-authored Wisdom
3. Define consistency model explicitly
4. Add race condition handling to T1 (locking strategy)
5. Define cascade depth limits
6. Specify T9 behavior: inline vs async for deep cascades

### Should Fix (Important)

1. Add T_LINK for explicit edge creation
2. Add T_DECAY or document implicit decay semantics
3. Define what happens when superseding node is tombstoned
4. Clarify T8 completion handling
5. Document ProposedBelief elimination as intentional EAG divergence

### Consider (Enhancement)

1. T_DEMOTE (promoted -> unpromoted on evidence withdrawal)
2. Semantic contradiction detection (LLM-based, queued)
3. Multi-agent consensus placeholder

---

## 10. Test Scenarios

The following scenarios should have defined outcomes before implementation:

1. **Double write race:** Two agents write same (s, p, o) simultaneously
2. **Supersession of tombstone:** Attempt to supersede already-tombstoned node
3. **Orphan belief:** All SYNTHESIZED_FROM facts tombstoned
4. **Cascade storm:** Core fact with 1000 dependents superseded
5. **Synthesis during staleness cascade:** T8 running when T9 marks inputs stale
6. **Cancel forget after GC:** Cancel attempted after hard delete
7. **Cross-silo link attempt:** Explicit link to node in different silo
8. **Self-corroboration:** Claim corroborates itself
9. **Restoration cascade:** Tombstoned node restored; what happens to superseding nodes?
10. **Query during synthesis:** RECALL while T8 in progress

Each scenario needs: expected outcome, invariant verification, error handling.
