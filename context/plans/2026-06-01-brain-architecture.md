# Brain Architecture Implementation Plan

**Status:** Ready to execute  
**Date:** 2026-06-01  
**Branch:** `feat/brain-architecture`

## Goal

Replace SAGE (cadence-based Dagster jobs) with a reactive brain architecture that enforces invariants at write-time, uses event-driven reactions instead of polling, and provides lazy synthesis on query.

## Scope

Implement the transaction layer defined in:
- `context/specs/brain-transactions-overview.md` (v3 tables)
- `context/specs/brain-transactions-pseudocode.md`

Core insight: value is in **retrieval with epistemic awareness**, not **autonomous belief formation**.

## Key Design Decisions

1. Write-time invariants - consistency enforced at write, not detected in batch
2. Event-driven reactions - not cadence-based Dagster jobs
3. Lazy synthesis - query-time with 2s timeout, not precomputed everything
4. Cascade depth limiting - max 10, depth-1 sync, rest async
5. ProposedBelief eliminated - use confidence threshold instead
6. Optimistic write + async consolidation - accept writes immediately, flag contradictions for background review, recall surfaces "unresolved conflict" state
7. Consolidation weighs evidence quality, recency, source authority - can merge/reconcile, not just pick-winner

## Tasks

### Phase 1: Core Write Path

1. [ ] TX0 STORE_MEMORY - basic observation storage with INV3 enforcement
2. [ ] TX2 STORE_CLAIM - claim with evidence, INV1/INV2 enforcement, optimistic locking
3. [ ] TX3 SUPERSEDE - version chain management, INV4 predecessor validation
4. [ ] TX17 LINK - typed relationship creation with INV7 validation

### Phase 2: Conflict Detection + Consolidation

5. [ ] FLAG_CONTRADICTION at write time - detect conflict, mark both nodes, emit consolidation event
6. [ ] CONSOLIDATE reaction - weigh evidence quality/recency/authority, merge or pick winner
7. [ ] Conflict status on nodes - unresolved/resolved/merged states surfaced in recall
8. [ ] CHECK_CORROBORATION helper - atomic N-of-M check (fix atomicity issue from review)
9. [ ] Define confidence formulas (missing from pseudocode)

### Phase 3: Belief Flow

8. [ ] TX4 SYNTHESIZE - cluster synthesis with lazy trigger
9. [ ] TX5 REVISE_BELIEF - belief update with staleness cascade
10. [ ] TX14 CRYSTALLIZE - WorkingHypothesis to Commitment
11. [ ] TX8 COMMIT - session hypothesis promotion

### Phase 4: Lifecycle

12. [ ] TX15 FORGET - request deletion with INV8 enforcement
13. [ ] TX16 CANCEL_FORGET - restore from pending deletion
14. [ ] TX10 HARD_DELETE - actual deletion (admin/GDPR)
15. [ ] CASCADE_STALENESS helper - depth-limited staleness propagation

### Phase 5: Layer Movement

16. [ ] TX18 PROMOTE - fact to belief promotion
17. [ ] TX19 DEMOTE - belief to fact demotion

### Phase 6: Query

18. [ ] RECALL query - with lazy synthesis trigger, engagement surfacing
19. [ ] COMPUTE_RECALL_SCORE helper - epistemic-aware ranking
20. [ ] Fix WOULD_CREATE_CYCLE query syntax bug

### Phase 7: CITE v2 Epistemology

21. [ ] Add `confidence` (propagated) and `credibility` (static) fields to nodes
22. [ ] Add weighted `SUPPORTS` and `CONTRADICTS` edges
23. [ ] Implement damped confidence propagation algorithm
24. [ ] Implement independence-weighted corroboration
25. [ ] Add PPR-based transitive scoring to recall
26. [ ] Consolidation subagent interface and prompt

### Phase 8: Reactions

27. [ ] Event queue infrastructure (silo-partitioned)
28. [ ] Worker pool with dynamic claiming
29. [ ] Migrate Dagster custodian/synthesizer logic to reactions

### Phase 9: Cleanup

30. [ ] Remove SAGE Dagster jobs (custodian, synthesizer, groundskeeper)
31. [ ] Archive SAGE code paths
32. [ ] Update docs

## Out of Scope / Deferred

| Item | Reason |
|------|--------|
| TX1 EXTRACT | LLM extraction pipeline - separate concern, keep existing |
| TX6 CONSENSUS | Multi-agent consensus - post-GTM |
| TX7 TRACE | Provenance queries - existing trace tool sufficient |
| TX11-13 ProposedBelief | Eliminated - use confidence threshold |
| Semantic conflict detection | INV1 covers structural only; semantic is research problem |
| Heat propagation formula params | PPR details defer to impl |

## Pseudocode Review Issues to Fix

1. **CHECK_CORROBORATION atomicity** - current pseudocode does two queries; need single atomic check
2. **Confidence formulas** - missing from pseudocode; define during Phase 2
3. **WOULD_CREATE_CYCLE query syntax** - parentheses bug in Cypher
4. **Consolidation policy** - spec how CONSOLIDATE weighs evidence quality, recency, source authority; when merge vs pick-winner

## Done Criteria

- [ ] All 9 invariants (INV1-9 per CITE v2) enforced at write time
- [ ] All Phase 1-6 transactions passing integration tests
- [ ] Event-driven reactions replacing Dagster cadence jobs
- [ ] Lazy synthesis working with 2s timeout
- [ ] SAGE Dagster jobs removed
- [ ] Damped confidence propagation working (CITE v2)
- [ ] Consolidation subagent resolving conflicts
- [ ] PPR-based transitive scoring in recall
- [ ] Performance targets met (recall cached < 20ms, search < 250ms, write < 300ms p95)

## Related

- Spec: `context/specs/brain-transactions-overview.md`
- Pseudocode: `context/specs/brain-transactions-pseudocode.md`
- Architecture draft: `context/specs/brain-architecture-draft.md`
- Reviews: `context/specs/brain-tables-review-v2.md`, `context/specs/brain-pseudocode-review.md`
- **CITE v2 Epistemology: `context/specs/cite-v2-epistemology.md`** - damped confidence propagation, weighted edges, subagent consolidation
