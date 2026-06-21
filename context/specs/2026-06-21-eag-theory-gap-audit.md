# EAG Theory Gap Audit

Date: 2026-06-21
Status: Audit complete, tracking implementation gaps
Related: 
- EAG Whitepaper (Khimani, 2026)
- context/specs/2026-06-06-write-quality-gate.md
- primitives/docs/06-epistemology.md

## Overview

Comprehensive audit of Engrammic implementation against EAG (Epistemic Augmented Generation) theory as specified in the whitepaper. Conducted via 6 parallel codebase analysis agents examining primitives and context-service.

The implementation is philosophically real (not cosmetic) — confidence is computed, promotion rules gate writes, PPR propagation runs. However, structural guarantees have gaps that affect the correctness claims in the whitepaper.

---

## Critical Gaps

These affect correctness and should block claims of AGM compliance or write-gate enforcement.

### GAP-001: Contradictions Pass Through at Write Time

**Spec:** EAG Table 4 — Knowledge layer requires semantic contradiction check; contradictions should be rejected with `rejection_reason: "contradiction"`.

**Implementation:** ~~`detect_spo_conflict` runs AFTER `store.execute_write` commits the node. Contradicting claims land as `ACTIVE` with `CONTRADICTS` edges and `conflict_status=unresolved`.~~

**Status:** FIXED (2026-06-21). Added pre-write contradiction check via `check_contradiction_before_write()`. When `contradiction_enforcement_enabled=True`, writes are rejected with `ContradictionRejected` error before commit. Setting defaults to `False` for backward compatibility.

**Priority:** P0
**Owner:** TBD
**Tracking:** [GAP-001]

---

### GAP-002: cascade_staleness Truncates at Depth 1

**Spec:** EAG Section 3.4 — supersession should "propagate through dependency graph deps(n)". Definition A.8 defines deps(n) as transitive closure.

**Implementation:** ~~`cascade_staleness` in sage/transactions.py has `MAX_CASCADE_DEPTH = 10` but the recursion guard at line 2927 exits after depth 1.~~

**Status:** FIXED (2026-06-21). Removed the erroneous `if depth == 1:` guard. Recursion now proceeds up to MAX_CASCADE_DEPTH.

**Priority:** P0
**Owner:** TBD
**Tracking:** [GAP-002]

---

### GAP-003: SYSTEM_CREATED_LABELS Unenforced

**Spec:** EAG Table 2 — Facts and Beliefs require system synthesis (3+ sources, derivation chains). Agents should not write these directly.

**Implementation:** ~~`SYSTEM_CREATED_LABELS` is defined in db/schema.py but never imported or checked.~~

**Status:** CLOSED (2026-06-21). Enforcement is architectural, not runtime. MCP tool surface maps to: `remember` → Memory, `learn` → Claim, `decide` → Commitment, `hypothesize` → WorkingHypothesis. No tool creates Facts or Beliefs. Creation queries (`CREATE_FACT`, `CREATE_BELIEF_FROM_FACTS`) exist only in SAGE internals (`engine/synthesis.py`, `engine/revision.py`, `sage/transactions.py`). Agent bypass is not possible through the API layer.

**Priority:** P1
**Tracking:** [GAP-003]

---

### GAP-004: No `status=superseded` on Knowledge Nodes

**Spec:** EAG Section 3.4 — superseded nodes should be "retained for audit" with status marking. AGM Recovery postulate requires original beliefs to be recoverable.

**Implementation:** `KnowledgeNode` dataclass in primitives/protocols.py has no `status` field. `SupersedeResult` only returns `superseded: bool`. No schema contract for stamping nodes.

**Impact:** Superseded nodes exist but are indistinguishable from active nodes at query time. Recovery path requires knowing node IDs — no systematic way to enumerate superseded beliefs.

**Fix:** Add `status: Literal["active", "superseded", "tombstoned"]` to KnowledgeNode. Update queries to filter by default.

**Priority:** P1
**Owner:** TBD
**Tracking:** [GAP-004]

---

### GAP-005: corroboration_factor Dropped from Credibility

**Spec:** primitives/docs/06-epistemology.md specifies:
```
credibility = source_tier × corroboration_factor × method_weight × raw_confidence
corroboration_factor = 1 - exp(-0.5 × n)
```

**Implementation:** ~~`sage/confidence.py::compute_credibility` uses only `source_tier × method_weight × raw_confidence`. The corroboration factor is absent.~~

**Status:** FIXED (2026-06-21). Added `corroboration_count` parameter and `corroboration_factor` computation to `compute_credibility`. Defaults to n=1 for backward compatibility.

**Priority:** P1
**Owner:** TBD
**Tracking:** [GAP-005]

---

## Significant Gaps

Implementation incomplete but not blocking correctness claims.

### GAP-006: Fact Requires Only 2 Sources (Spec Says 3)

**Spec:** EAG Definition A.3 — E(F) requires 3+ independent sources.

**Implementation:** R2 promotion rule in primitives/eag/promotion.py only requires `>= 2` claims.

**Fix:** Update R2 threshold or implement R3 rule.

**Priority:** P2
**Tracking:** [GAP-006]

---

### GAP-007: No Derivation Chain Validation for Beliefs

**Spec:** EAG Table 2 — Beliefs require derivation chain evidence.

**Implementation:** `validate_node_for_promotion` only checks `has_citations` boolean, not chain completeness.

**Fix:** Add derivation chain validator in promotion predicates.

**Priority:** P2
**Tracking:** [GAP-007]

---

### GAP-008: Hypothesis Type Killed, No Replacement

**Spec:** EAG Table 2 — Hypothesis is a distinct epistemic type in Intelligence layer.

**Implementation:** `WorkingHypothesis` marked `# killed` in labels_v2.py, listed in DEPRECATED_LABELS.

**Fix:** Either restore Hypothesis or document why it's unnecessary.

**Priority:** P3
**Tracking:** [GAP-008]

---

### GAP-009: No Warrant Function w(n)

**Spec:** EAG Definition A.4 — warrant function mapping evidence to confidence.

**Implementation:** No function named `warrant` exists. `combined_confidence` is closest but incomplete.

**Fix:** Implement canonical warrant function per spec formula.

**Priority:** P2
**Tracking:** [GAP-009]

---

### GAP-010: No deps(n) Traversal Function

**Spec:** EAG Definition A.8 — deps(n) = {m | DERIVED_FROM(m,n) ∨ SUPPORTS(m,n)}

**Implementation:** ~~`should_supersede` operates on single pairs. No function walks the dependency graph for propagation.~~

**Status:** FIXED (2026-06-21). Added `primitives.eag.epistemology.propagation` module with:
- `DependencyEdgeType` enum (DERIVED_FROM, SUPPORTS, SYNTHESIZED_FROM)
- `direct_dependents(node_id, edges)` — depth-1 dependents
- `compute_deps(node_id, edges, max_depth)` — transitive closure via BFS

Context-service fetches edges from graph DB and passes to pure functions.

**Priority:** P1
**Tracking:** [GAP-010]

---

### GAP-011: R3/R4 Promotion Rules Are Stubs

**Spec:** Promotion ladder should have context-sensitive and temporal rules.

**Implementation:** R3 and R4 exist in PromotionRule enum but are marked "Reserved for future" with no implementation.

**Fix:** Implement or remove from enum.

**Priority:** P3
**Tracking:** [GAP-011]

---

### GAP-012: No NCB (Neighborhood Consistency) Check

**Spec:** EAG Table 4 — Wisdom layer requires NCB check before write.

**Implementation:** `_run_incremental_propagation` is confidence update, not consistency gate. `neighborhood_inconsistent` is not a rejection reason.

**Fix:** Implement NCB check in WriteQualityGate.

**Priority:** P2
**Tracking:** [GAP-012]

---

### GAP-013: No DERIVED_FROM Cycle Detection

**Spec:** EAG C3 invariant — DERIVED_FROM must be acyclic.

**Implementation:** `_would_create_cycle` only covers SUPERSEDES and hierarchical edges. Line 2399-2400:
```python
if edge_type != "SUPERSEDES": return False
```

**Fix:** Extend cycle detection to DERIVED_FROM edges.

**Priority:** P2
**Tracking:** [GAP-013]

---

### GAP-014: INV1 (No Contradictions) Is Feature-Flagged

**Spec:** EAG Table 7 — INV1 enforced at write + T2.

**Implementation:** `contradiction_flagging_enabled` is a feature flag. When false, conflicting claims are not blocked.

**Fix:** Make INV1 enforcement mandatory, not optional.

**Priority:** P2
**Tracking:** [GAP-014]

---

### GAP-015: INV3 Not Re-validated Post-Tombstone

**Spec:** EAG Table 7 — Beliefs have >= N fact sources.

**Implementation:** Enforced at synthesis time but not after. If source facts are tombstoned, Belief can fall below N-fact floor without re-validation.

**Fix:** Add post-tombstone cascade that re-validates or tombstones orphaned Beliefs.

**Priority:** P2
**Tracking:** [GAP-015]

---

## Minor Gaps

Spec drift and edge label mismatches. Low priority but should be reconciled.

### GAP-016: T1 Stores EXTRACTED_FROM Not DERIVED_FROM

**Spec:** EAG Table 6 — T1 provenance should be DERIVED_FROM.

**Implementation:** reactions/tasks.py:814 writes `EXTRACTED_FROM`. Mapped in display queries but graph edge differs.

**Priority:** P3
**Tracking:** [GAP-016]

---

### GAP-017: T13 Stores CRYSTALLIZED_FROM (Direction Inverted)

**Spec:** EAG Table 6 — T13 provenance should be CRYSTALLIZED_INTO.

**Implementation:** db/queries.py:1746 writes `CRYSTALLIZED_FROM`. Direction is `(Commitment)-[:CRYSTALLIZED_FROM]->(WorkingHypothesis)` vs spec's `CRYSTALLIZED_INTO`.

**Priority:** P3
**Tracking:** [GAP-017]

---

### GAP-018: T3 Synthesis Is Batch, Not Signal-Driven

**Spec:** EAG Table 6 — T3 trigger is "signal when cluster density >= N".

**Implementation:** `belief_synthesis_asset` is a Dagster scheduled batch job, not real-time signal.

**Priority:** P3
**Tracking:** [GAP-018]

---

### GAP-019: FindingHistory Hard-Deletes After 20 Revisions

**Spec:** AGM Recovery — original beliefs should be recoverable.

**Implementation:** `FINDING_HISTORY_TRIM` uses `DETACH DELETE` on snapshots beyond `$keep` (default 20).

**Impact:** Violates AGM Recovery for beliefs revised 20+ times.

**Priority:** P3
**Tracking:** [GAP-019]

---

## What's Solid

These components align with EAG theory:

| Component | Status | Location |
|-----------|--------|----------|
| 4-layer hierarchy | Fully modeled | primitives/schema/labels.py, labels_v2.py |
| Evidence requirement (Memory->Knowledge) | Hard-enforced | sage/transactions.py (MissingEvidenceError) |
| Cross-silo rejection (INV5) | Hard-enforced | sage/transactions.py (CrossSiloViolation) |
| SUPERSEDES cycle detection (INV4) | Full | db/queries.py, mcp/tools/context_store.py |
| Tombstone invisibility (INV6) | Full | engine/qdrant_store.py:313, retrieval/fusion.py |
| DECLARED_BY on commitments (INV7) | Full | db/queries.py:1712, services/context.py:1291 |
| Cancel window (INV8) | Full | retention/forget_service.py |
| Confidence math | Real computation | primitives/eag/epistemology/confidence.py |
| PPR propagation | Implemented | sage/epistemology.py |
| Promotion rules R1/R2 | Structural gates | custodian/fact_promotion.py |

---

## Recommended Priority Order

1. ~~**GAP-001** — Write-gate contradiction rejection~~ FIXED 2026-06-21
2. ~~**GAP-002** — cascade_staleness depth fix~~ FIXED 2026-06-21
3. ~~**GAP-010** — deps(n) traversal~~ FIXED 2026-06-21 (primitives propagation module)
4. ~~**GAP-004** — status=superseded marking~~ FIXED 2026-06-21 (earlier session)
5. ~~**GAP-005** — corroboration_factor in credibility~~ FIXED 2026-06-21
6. ~~**GAP-003** — SYSTEM_CREATED_LABELS enforcement~~ CLOSED 2026-06-21 (architectural)

---

## Appendix: Audit Methodology

Six parallel Sonnet subagents examined:
1. Primitives: epistemic types and evidence requirements
2. Primitives: supersession and AGM compliance
3. Context-service: write-gate implementation
4. Context-service: transition catalog (T1-T15)
5. Context-service: coherence invariants (INV1-INV8)
6. Cross-repo: philosophical/design gaps

Related arXiv research surveyed (June 2026):
- Kumiho (2603.17244) — parallel AGM compliance work
- BeliefTrack/CBM (2605.30219) — belief revision benchmarks
- AI Scientists (2604.18805) — empirical epistemology gap data
