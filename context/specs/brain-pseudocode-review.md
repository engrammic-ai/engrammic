# Brain Pseudocode Review

**Reviewer:** Claude  
**Date:** 2026-06-01

---

## 1. Tables-to-Pseudocode Alignment

**Good:** TX0, TX2, TX3, TX4, TX5, TX8, TX10, TX14-19, RECALL all match the overview tables.

**Mismatches:**
- TX2 lock scope: overview says `(silo_id, subject, predicate)` optimistic lock - pseudocode does this correctly
- TX11-13 (ProposedBelief): overview marks them as possibly eliminated, pseudocode confirms elimination - consistent
- TX1, TX6, TX7, TX9: correctly marked as deferred in pseudocode

## 2. Logic Errors

- **WOULD_CREATE_CYCLE bug (line 412):** Query uses `current.id = current` - should be `WHERE id = $current`
- **CHECK_CORROBORATION mutation outside transaction:** Updates corroboration_count on multiple claims without atomicity
- **TX5 return type mismatch:** Returns `Ok(belief_id)` on no-change path but signature says `new_belief_id` - acceptable but document

## 3. Missing Pieces

- `extract_spo()` - NLP/structured extraction not defined (acceptable, implementation detail)
- `compute_initial_confidence()`, `recompute_confidence()` - need formulas
- `noisy_or_aggregate()` - referenced but not defined
- `session_expiry()`, `current_session_id()` - session management undefined
- `AUDIT_LOG` - append-only store not specified
- `count_distinct_documents()` vs `count_distinct_evidence_sources()` - inconsistent naming

## 4. Invariant Enforcement

| INV | Status | Notes |
|-----|--------|-------|
| INV1 | Enforced | TX2 conflict detection + resolution |
| INV2 | Enforced | TX2 validates memory evidence, creates DERIVED_FROM |
| INV3 | Enforced | TX4 checks SYNTHESIS_THRESHOLD |
| INV4 | Enforced | WOULD_CREATE_CYCLE called in TX3, TX17 |
| INV5 | Enforced | All cross-silo checks present |
| INV6 | Enforced | RECALL filters tombstoned |
| INV7 | Enforced | TX8, TX14 create DECLARED_BY |
| INV8 | Enforced | TX16 checks cancel_window_expires |

**Gap:** INV2 mentions PROMOTED_FROM for consensus path - TX6 is deferred, so this edge type doesn't appear.

## 5. Consistency Across Transactions

- TX2 -> CHECK_CORROBORATION -> TX18: Works correctly
- TX4/TX5 cluster lock coordination: Sound
- CASCADE_STALENESS -> TX5: Proper async handoff
- TX15 -> CASCADE_FORGET: Correct depth-first traversal
- **Issue:** CHECK_CORROBORATION calls TX18 synchronously in caller's transaction context - could cause nested lock issues if TX18 acquires claim_id lock while TX2 holds SPO lock

## 6. Implementation Readiness

**Score: 4/5**

Ready to implement with minor gaps:
- Define confidence computation formulas
- Define noisy_or_aggregate
- Fix WOULD_CREATE_CYCLE query syntax
- Add session management interface

## 7. Top 3 Issues

1. **CHECK_CORROBORATION non-atomic updates** - Multiple claim updates without transaction boundary; could leave inconsistent corroboration counts on partial failure

2. **Missing confidence formulas** - `compute_initial_confidence`, `recompute_confidence`, `noisy_or_aggregate` are critical for correctness but undefined

3. **WOULD_CREATE_CYCLE query syntax error** - Line 412 `current.id = current` is invalid; blocks cycle detection
