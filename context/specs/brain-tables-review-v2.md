# Brain Tables Specification Review v2

**Status:** REVIEW  
**Date:** 2026-06-01  
**Spec version reviewed:** v2

---

## 1. Blocker Verification

| Blocker | Status | Notes |
|---------|--------|-------|
| TX0 STORE_MEMORY missing | FIXED | Added to Sections 5, 6, 7 |
| TX19 DEMOTE inconsistent | FIXED | Now in all tables with lock scope fact_id |
| Cluster definition missing | FIXED | Section 4.5 covers membership, states, computation |
| Lock strategy undefined | FIXED | Lock scope column added to Section 6 |
| Test scenario outcomes TBD | FIXED | All 19 scenarios have concrete outcomes |
| Restoration cascade unaddressed | FIXED | Section 10 includes explicit rules, preserves supersession history |

**All 6 blockers resolved.**

---

## 2. New Issues Introduced

1. **TX2 lock scope notation unclear** - "(silo, s, p) optimistic" uses unexplained shorthand. Assume s=subject, p=predicate, but should be explicit.

2. **Cluster entity vs cluster state mismatch** - Entity table (Section 1) lists Cluster as Meta layer entity. Section 4.5 defines cluster states (SPARSE/READY/SYNTHESIZED/STALE). These states should be referenced in the Entity table.

3. **STALE transition ambiguity** - Section 4.5 says STALE transitions to "READY (re-synth), SYNTHESIZED" - should only be READY, then READY->SYNTHESIZED after synthesis completes.

---

## 3. Remaining Gaps

| Gap | Impact |
|-----|--------|
| WorkingHypothesis cleanup mechanism | Medium - expiry mentioned but no TX handles session-end cleanup |
| INV2 for TX6 CONSENSUS | Low - consensus Facts come from ReasoningChains, not Memory; does this satisfy DERIVED_FROM requirement? |
| Semantic conflict detection | Low - INV1 covers structural (s,p,o) conflicts only |
| Heat propagation formula | Low - PPR mentioned but no damping/iteration params |

---

## 4. Internal Consistency Check

**Cluster integration with TX4/TX11:** Coherent. TX4 inputs cluster_id, Section 4.5 READY->SYNTHESIZED matches. TX11 PROPOSE uses same cluster_id pattern for weak synthesis.

**Section 12 decisions:** "ProposedBelief eliminated" documented. Section 4.5 cluster states don't reference ProposedBelief. Consistent.

**Lock scope alignment:** TX4/TX11 both lock cluster_id. TX18 PROMOTE locks claim_id. TX19 DEMOTE locks fact_id. No conflicts.

**EAG T1-T15 mapping:** All 15 transitions from 03-transitions.md are covered by TX1-TX19.

---

## 5. Ready for Pseudocode?

**YES**

The spec covers all transactions, states, invariants, cascades, and test outcomes. Remaining gaps are edge cases resolvable during implementation with TODO markers.

---

## 6. Clarifications Needed (not blockers)

1. Expand TX2 lock scope "(silo, s, p)" notation
2. Add cluster states to Entity table or cross-reference Section 4.5
3. Confirm TX6 satisfies INV2 or document exemption
4. Fix STALE transition (should only go to READY)
