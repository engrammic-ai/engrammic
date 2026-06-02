# Brain Transactions: High-Level Overview

> Tables-first specification. Pseudocode comes later.

**Status:** DRAFT v3  
**Date:** 2026-06-01

### Changelog

- v3: Fixed TX2 lock scope notation, added cluster states cross-reference to entity table, fixed STALE->READY transition (not direct to SYNTHESIZED), updated INV2 to include PROMOTED_FROM for consensus path.
- v2: Added TX0 STORE_MEMORY, cluster definition, lock strategy, test scenario outcomes, restoration cascade, decision point rationales. Fixed TX19 DEMOTE consistency. Added Agent/Cluster entities.
- v1: Initial tables covering EAG T1-T15.

---

## 1. Entity Types

| Entity | Layer | Description | Can be superseded? | Can be tombstoned? | Created by |
|--------|-------|-------------|--------------------|--------------------|------------|
| Document | Memory | Ingested source file | No | Yes | Ingestion |
| Passage | Memory | Chunk within document | No | Yes | Ingestion |
| Utterance | Memory | Conversation turn | No | Yes | TX0 |
| Observation | Memory | Agent observation | No | Yes | TX0 |
| Event | Memory | System occurrence | No | Yes | System |
| Claim | Knowledge | Extracted proposition (unpromoted) | Yes | Yes | TX1, TX2 |
| Fact | Knowledge | Promoted claim (corroborated) | Yes | Yes | TX18 (from Claim) |
| Belief | Wisdom | System-synthesized judgment | Yes | Yes | TX4 |
| Commitment | Wisdom | Agent-declared stance | Yes | Yes | TX8, TX14 |
| Pattern | Wisdom | Detected recurring shape | Yes | Yes | TX4 (variant) |
| WorkingHypothesis | Intelligence | In-progress reasoning (session-scoped) | No | No (expires) | TX_HYPOTHESIZE |
| ReasoningChain | Intelligence | Stored reasoning sequence | No | Yes | TX7 |
| Agent | Meta | System or human agent identity | No | No | Registration |
| Cluster | Meta | Grouping of related facts for synthesis (see Section 4.5 for states: SPARSE/READY/SYNTHESIZED/STALE) | No | No | Computed |

---

## 2. Node States

| State | Meaning | Queryable? | Mutable? | Transitions to |
|-------|---------|------------|----------|----------------|
| ACTIVE | Live, current | Yes | Yes | SUPERSEDED, TOMBSTONED |
| SUPERSEDED | Replaced by newer version | Only with as_of query | No | TOMBSTONED |
| TOMBSTONED | Soft deleted, in cancel window | No | Only cancel | ACTIVE (cancel), DELETED |
| DELETED | Hard deleted, gone | No | No | (terminal) |

### State Diagram

```
            ┌─────────────────────────────────────┐
            │                                     │
            v                                     │
[create] ─> ACTIVE ──supersede──> SUPERSEDED     │
              │                        │          │
              │                        │          │
              └───forget───> TOMBSTONED <─forget──┘
                                │    │
                         cancel │    │ GC
                                v    v
                             ACTIVE  DELETED
```

---

## 3. Claim Lifecycle (within ACTIVE state)

| Status | Meaning | Transitions to |
|--------|---------|----------------|
| UNPROMOTED | Raw claim, not yet corroborated | PROMOTED |
| PROMOTED | Became Fact (threshold met) | (stays promoted, or DEMOTED if evidence withdrawn) |

---

## 4. Belief Lifecycle (within ACTIVE state)

| Status | Meaning | Transitions to |
|--------|---------|----------------|
| FRESH | Synthesis current, evidence unchanged | STALE |
| STALE | Evidence changed, needs re-synthesis | FRESH (re-synth), INVALIDATED |
| INVALIDATED | Evidence removed, unsupported | (tombstone or re-synth if new evidence) |

---

## 4.5 Cluster Definition

A **cluster** is a set of Facts that are candidates for synthesis into a Belief.

### Cluster Properties

| Property | Value |
|----------|-------|
| Membership | Facts within embedding distance D of centroid, same silo |
| Minimum size | N facts (synthesis threshold, default 3) |
| Maximum size | Configurable (default 1000, prevents synthesis cost explosion) |
| Recomputation | Incremental on fact creation, periodic batch refresh |
| Overlap | A fact may belong to multiple clusters |

### Cluster States

| State | Meaning | Transitions to |
|-------|---------|----------------|
| SPARSE | Below minimum fact count | READY (when threshold met) |
| READY | Density threshold met, awaiting synthesis | SYNTHESIZED (after TX4 completes) |
| SYNTHESIZED | Has active Belief linked | STALE (when source facts change) |
| STALE | Source facts changed since synthesis | READY (triggers re-synthesis via TX5) |

### Cluster Computation

| Aspect | Approach |
|--------|----------|
| Algorithm | Embedding similarity (cosine distance < D) |
| Centroid | Mean of member fact embeddings |
| Update trigger | New fact stored, fact superseded, fact tombstoned |
| Staleness detection | Any member fact changed since last synthesis |

---

## 5. All Transactions (mapped to EAG T1-T15)

| ID | Name | EAG Ref | Trigger | Layer transition | Sync/Async |
|----|------|---------|---------|------------------|------------|
| TX0 | STORE_MEMORY | - | Agent calls `remember` | -> Memory | Sync |
| TX1 | EXTRACT | T1 | Document ingested or hot passage | Memory -> Knowledge | Async |
| TX2 | STORE_CLAIM | - | Agent calls `learn` | -> Knowledge | Sync |
| TX3 | SUPERSEDE | T2 | Conflict detected OR agent revises | Knowledge -> Knowledge | Sync |
| TX4 | SYNTHESIZE | T3 | Cluster ready OR query-time | Knowledge -> Wisdom | Async (or sync on query) |
| TX5 | REVISE_BELIEF | T4 | Evidence distribution shift | Wisdom -> Wisdom | Async |
| TX6 | CONSENSUS | T5 | K chains from J agents agree | Intelligence -> Knowledge | Async |
| TX7 | TRACE | T6 | Reasoning chain completes | Intelligence -> Memory | Async |
| TX8 | COMMIT | T7 | Agent declares stance | Intelligence -> Wisdom | Sync |
| TX9 | DECAY | T8 | Time passes (query-time compute) | Memory -> (weight 0) | Implicit |
| TX10 | HARD_DELETE | T9 | Age threshold OR GDPR | Any -> deleted | Async (scheduled) |
| TX11 | PROPOSE | T10 | Weak synthesis confidence | Knowledge -> Wisdom (proposed) | Async |
| TX12 | ACCEPT | T11 | Proposal validated | Wisdom (proposed) -> Wisdom | Sync |
| TX13 | REJECT | T12 | Proposal rejected | Wisdom (proposed) -> tombstone | Sync |
| TX14 | CRYSTALLIZE | T13 | Agent crystallizes hypothesis | Intelligence -> Wisdom | Sync |
| TX15 | FORGET | T14 | Agent calls `forget` | Any -> tombstone | Sync |
| TX16 | CANCEL_FORGET | T15 | Agent calls within window | Tombstone -> ACTIVE | Sync |
| TX17 | LINK | - | Agent calls `link` | Creates edge | Sync |
| TX18 | PROMOTE | - | Corroboration threshold met | Claim -> Fact | Sync |
| TX19 | DEMOTE | - | Evidence withdrawn | Fact -> Claim | Sync |

**Note:** TX11-TX13 (ProposedBelief flow) may be eliminated. Document as intentional if so.

---

## 6. Transaction Detail: Inputs, Outputs, Failures

| TX | Inputs | Outputs | Can fail? | Failure handling | Lock scope |
|----|--------|---------|-----------|------------------|------------|
| TX0 STORE_MEMORY | content, tags, silo_id | node_id | No | - | None |
| TX1 EXTRACT | document_id, passage_id | claim[] | Yes (LLM) | Retry, dead letter | None |
| TX2 STORE_CLAIM | content, evidence_refs, silo_id | node_id | Yes (invariant) | Reject write | (silo_id, subject, predicate) optimistic lock; retry on conflict |
| TX3 SUPERSEDE | winner_id, loser_id, reason | edge | No | - | loser_id |
| TX4 SYNTHESIZE | cluster_id | belief_id or null | Yes (LLM) | Retry, skip | cluster_id |
| TX5 REVISE_BELIEF | belief_id | new_belief_id | Yes (LLM) | Mark stale, retry | belief_id |
| TX6 CONSENSUS | chain_ids[] | fact_id | No | - | None |
| TX7 TRACE | chain_id | memory_node_id | No | - | None |
| TX8 COMMIT | content, about_refs | commitment_id | Yes (invariant) | Reject | None |
| TX9 DECAY | (implicit) | updated weight | No | - | None (query-time) |
| TX10 HARD_DELETE | node_ids[] | deleted count | No | - | node_ids (batch) |
| TX11 PROPOSE | cluster_id | proposed_belief_id | Yes (LLM) | Skip | cluster_id |
| TX12 ACCEPT | proposed_id | belief_id | No | - | proposed_id |
| TX13 REJECT | proposed_id, reason | tombstone | No | - | proposed_id |
| TX14 CRYSTALLIZE | hypothesis_id | commitment_id | Yes (invariant) | Reject | hypothesis_id |
| TX15 FORGET | node_id, reason? | tombstone | No | - | node_id |
| TX16 CANCEL_FORGET | node_id | restored node | Yes (window expired) | Return error | node_id |
| TX17 LINK | source_id, target_id, type | edge | Yes (invariant) | Reject | (source, target) |
| TX18 PROMOTE | claim_id | updated claim (Fact) | No | - | claim_id |
| TX19 DEMOTE | fact_id | updated claim | No | - | fact_id |

---

## 7. Sync vs Async Boundary

### Must be Sync (blocks caller)

| Transaction | Why sync? |
|-------------|-----------|
| TX0 STORE_MEMORY | Caller needs node_id, simple write |
| TX2 STORE_CLAIM | Caller needs node_id, must enforce invariants |
| TX3 SUPERSEDE | Part of write path, consistency critical |
| TX8 COMMIT | Agent expects immediate persistence |
| TX14 CRYSTALLIZE | Agent expects immediate persistence |
| TX15 FORGET | Agent expects immediate effect |
| TX16 CANCEL_FORGET | Time-sensitive, must respond immediately |
| TX17 LINK | Caller needs confirmation |
| TX18 PROMOTE | Part of write-time reaction chain |

### Must be Async (background)

| Transaction | Why async? |
|-------------|-----------|
| TX1 EXTRACT | LLM-based, expensive, can't block ingestion |
| TX4 SYNTHESIZE | LLM-based, expensive |
| TX5 REVISE_BELIEF | LLM-based, triggered by evidence shift |
| TX6 CONSENSUS | Aggregates across sessions, not real-time |
| TX7 TRACE | Post-session cleanup |
| TX10 HARD_DELETE | Scheduled GC |
| TX11 PROPOSE | LLM-based weak synthesis |

### Can be Either (policy decision)

| Transaction | Tradeoff |
|-------------|----------|
| TX4 SYNTHESIZE (on query) | Sync = latency hit; Async = stale results |
| TX12 ACCEPT | Could be background validation or immediate |
| TX13 REJECT | Same as ACCEPT |
| TX19 DEMOTE | Could be lazy or eager |

---

## 8. Invariants

| ID | Invariant | Enforced by | Enforcement timing |
|----|-----------|-------------|-------------------|
| INV1 | No contradicting ACTIVE claims (same silo, s, p, different o) | TX2 + TX3 | Write-time |
| INV2 | Every Fact has >= 1 DERIVED_FROM to Memory OR PROMOTED_FROM to ReasoningChain | TX2, TX18, TX6 | Write-time |
| INV3 | Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts | TX4 | Synthesis-time |
| INV4 | SUPERSEDES edges are acyclic | TX3 | Write-time (check before create) |
| INV5 | No cross-silo edges | TX2, TX17, TX4 | Write-time |
| INV6 | Tombstoned nodes invisible to RECALL | Query layer | Query-time filter |
| INV7 | Every Commitment has DECLARED_BY edge to agent | TX8, TX14 | Write-time |
| INV8 | Cancel window is time-bounded | TX16 | Check on cancel attempt |

---

## 9. Reactions (what triggers what)

| Event | Immediate reactions (sync) | Deferred reactions (async) |
|-------|---------------------------|---------------------------|
| Memory stored (TX0) | None | Update heat, check extraction trigger |
| Claim stored (TX2) | Check consistency, check corroboration | Update heat |
| Conflict detected | Resolve (TX3) | - |
| Node superseded (TX3) | - | Cascade staleness |
| Corroboration threshold met | Promote (TX18) | Check synthesis trigger |
| Cluster density crossed | - | Enqueue synthesis (TX4) |
| Belief marked stale | - | Enqueue re-synthesis (TX5) |
| Evidence edge removed | - | Check belief validity (INV3) |
| Node tombstoned (TX15) | Start cancel window | Cascade to dependents |
| Cancel window expired | - | Eligible for hard delete |
| Document ingested | - | Enqueue extraction (TX1) |

---

## 10. Cascade Behavior

| Cascade type | Trigger | Propagation | Depth limit | Async? |
|--------------|---------|-------------|-------------|--------|
| Staleness | Node superseded or tombstoned | To nodes with SYNTHESIZED_FROM or DERIVED_FROM pointing to changed node | 10 | Depth 1 sync, rest async |
| Corroboration recalc | Corroborating claim removed | To claims with same (s, p, o) | 1 | Sync |
| Belief invalidation | All source facts gone | To belief only | 1 | Sync |
| Heat propagation | Any access | PPR diffusion | Configurable | Async |
| Restoration | Node restored (TX16) | Re-evaluate dependents that were cascade-tombstoned | 10 | Async |

### Cascade Deduplication

Diamond dependencies (A -> B, A -> C, B -> D, C -> D) mark D stale once, not twice:
- Track visited nodes during cascade
- Skip already-visited nodes
- Use cascade_id for resumption on interruption

### Restoration Cascade Rules

When a tombstoned node is restored via TX16:
1. Node returns to ACTIVE state
2. Dependents that were cascade-tombstoned are NOT auto-restored (intentional)
3. Staleness markers set because of this node are cleared
4. If node was superseder: loser stays SUPERSEDED (history preserved)
5. If node was superseded: no change to superseder

---

## 11. Consistency Model

| Property | Guarantee | Scope |
|----------|-----------|-------|
| Read-your-writes | Yes | Within silo, same agent |
| Causal consistency | No | Cross-agent ordering not guaranteed |
| Strong consistency | Yes for sync TX | Write path (TX2, TX3, etc.) |
| Eventual consistency | Yes for async TX | Synthesis, extraction, cascades |
| Conflict resolution | Deterministic | Structural rules, then LLM tiebreaker |

---

## 12. Decision Points

| Question | Options | Decision | Rationale |
|----------|---------|----------|-----------|
| ProposedBelief flow (TX11-13)? | Keep / Eliminate | **Eliminate** | Use confidence threshold instead; simplifies state machine |
| Lazy synthesis on query? | Yes / No | **Yes, 2s timeout** | Return facts + "synthesis_pending" on timeout |
| Cascade depth limit? | N = ? | **10** | Also consider node count limit (1000) |
| Idle-time threshold? | N seconds | **60s per silo** | Configurable per deployment |
| Conflict tiebreaker? | Timestamp / LLM / Reject | **Timestamp** | Older wins for stability; same-agent newer wins |
| Demote on evidence withdrawal? | Yes / No | **Yes** | Maintains semantic integrity |
| Cancel window duration? | N minutes | **60 min** | Configurable per silo for enterprise |
| Synthesis confidence threshold? | N = ? | **0.6** | Below this, don't create Belief; log and retry when more evidence |

---

## 13. Test Scenarios

| Scenario | Expected outcome | Invariants checked |
|----------|------------------|-------------------|
| Two agents write same (s,p,o) simultaneously | Second writer gets CONFLICT error with winner_id; must retry with supersedes param | INV1 |
| Supersede a tombstoned node | Reject with INVALID_STATE error | - |
| All SYNTHESIZED_FROM facts tombstoned | Belief state -> INVALIDATED; eligible for tombstone on next GC | INV3 |
| Core fact with 1000 dependents superseded | Depth-1 (direct dependents) sync; rest enqueued async with rate limit (100/s) | - |
| Cancel forget after window | Return WINDOW_EXPIRED error; node stays tombstoned | INV8 |
| Cross-silo link attempt | Reject with CROSS_SILO_VIOLATION error | INV5 |
| Query during active synthesis | Return facts + metadata `{synthesis_status: "in_progress", cluster_id: X}` | - |
| Tombstoned node's superseder tombstoned | Loser stays SUPERSEDED (no auto-revival; history preserved) | INV4 |
| LLM synthesis timeout (>2s) | Mark cluster STALE; enqueue retry with exponential backoff (max 3 attempts) | - |
| Evidence URL 404 | Store claim with `evidence_status: "unverified"`, confidence *= 0.5 | INV2 |
| Agent stores then immediately recalls | Read-your-writes guaranteed; node visible in same-agent query | - |
| Concurrent synthesis for same cluster | Deduplicate; second request waits for first result | - |
| Circular evidence (A cites B, B cites A) | Reject second write with CIRCULAR_REFERENCE error | - |
| Belief from single fact (below N) | Synthesis skipped; cluster stays SPARSE | INV3 |
| Same-agent conflict (revision) | Newer wins (agent correcting self); create SUPERSEDES edge | INV1 |
| GDPR delete with dependents | Cascade tombstone all dependents; bypass cancel window | - |
| Restore node that was cascade-tombstoned source | Source restored; cascade-tombstoned dependents stay tombstoned (manual restore needed) | - |

---

## 14. What Dies from Current SAGE

| Component | Replacement |
|-----------|-------------|
| sage.custodian (scheduled extraction) | TX1 EXTRACT (event-driven) |
| sage.synthesizer (scheduled synthesis) | TX4 SYNTHESIZE (event/query-driven) |
| sage.validator (batch accept/reject) | TX12/TX13 or eliminated |
| sage.groundskeeper | TX10 HARD_DELETE + decay (mostly unchanged) |
| Dagster jobs | Event queue workers |
| ProposedBelief ceremony | Eliminated (or simplified) |
| 4-phase LLM visits | Single-purpose transactions |

---

## 15. What's New

| Component | Purpose |
|-----------|---------|
| Write-time invariant checks | Consistency as invariant, not validation |
| Event queue (per-silo partitioned) | Replaces scheduled jobs |
| Idle detection | Triggers consolidation ("dreaming") |
| Query-time synthesis | Lazy synthesis with caching |
| Cascade depth limiting | Prevents storms |
| Explicit consistency model | Documented guarantees |

---

## Next Steps

1. Review tables for completeness
2. Decide on TBD decision points (section 12)
3. Define outcomes for test scenarios (section 13)
4. Then: expand individual transactions to pseudocode
