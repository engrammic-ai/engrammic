# Epistemic Hygiene: Pre-Fix, Parallel Track, and Convergence Plan

Date: 2026-06-11
Source: `context/review/2026-06-11-architecture-epistemics-critique.md` (full critique, items A1-A4, E1-E9, D1-D5)
Constraint: the Monday 2026-06-15 sprint gate (`2026-06-11-defensibility-sprint.md`) is untouchable. The court verdict documented twice that architecture work displaces the proof artifact; this plan exists to PREVENT that, not enable it. Hard caps below are not suggestions.

## Tier 1: PRE-FIX (before/with step 1, hard cap: half a day)

> Executor-ready plan: `context/plans/2026-06-11-prefix-confidence-hygiene-plan.md` (full TDD task breakdown for H1+H2, written for a fresh agent). The sections below are the rationale; the executor plan is the source of truth for implementation.

Only items that step 1 would otherwise build on top of incorrectly.

### H1. Canonical confidence reader + the falsy-zero bug (DONE - see 2026-06-11-prefix-confidence-hygiene-plan.md)

Verified bug on the live path: `float(props.get("confidence") or 1.0)` at `services/context.py:806, 816, 854, 1491` maps confidence == 0.0 to 1.0. A zero-confidence node reads as fully trusted; step-1 fusion would then refuse to demote it because the value is corrupted upstream of fusion. Additionally `sage/recall.py` disagrees with itself (default 1.0 at :132, 0.0 at :345 and :412) - dead path, fix opportunistically at cutover, not now.

Fix: one helper, all live read sites use it.

Create `src/context_service/engine/epistemics.py`:

```python
"""Canonical interpretation of epistemic node properties.

Single source of truth for what ABSENT epistemic state means.
Convention (matches apply_trust_gate): missing confidence is None -
never penalized, never boosted. Present confidence (including 0.0)
is respected as-is.
"""

from __future__ import annotations

from typing import Any


def read_confidence(props: dict[str, Any]) -> float | None:
    """Return the node's confidence, or None when never assessed.

    Never use `props.get("confidence") or default`: that maps a stored
    0.0 (assessed, zero confidence) to the default (falsy bug).
    """
    raw = props.get("confidence")
    if raw is None:
        return None
    return max(0.0, min(1.0, float(raw)))


def effective_confidence(props: dict[str, Any], *, when_missing: float = 1.0) -> float:
    """Confidence for contexts that need a scalar. Missing -> when_missing.

    when_missing=1.0 is the trust-gate convention (do not penalize absent
    data). Callers MUST NOT pass when_missing=0.0 on read paths; treating
    unassessed as worthless is a ranking decision, not a data default.
    """
    conf = read_confidence(props)
    return when_missing if conf is None else conf
```

Replace the four live call sites in `services/context.py` (806, 816, 854, 1491) with `effective_confidence(props)` / `effective_confidence(r)`. Line 655 (`row.get("confidence", 1.0)`) is dict-default style but same semantics - use the helper there too.

Test (`tests/engine/test_epistemics.py`):

```python
from context_service.engine.epistemics import effective_confidence, read_confidence


class TestReadConfidence:
    def test_missing_is_none(self) -> None:
        assert read_confidence({}) is None

    def test_zero_is_zero_not_default(self) -> None:
        # The falsy bug this module exists to kill.
        assert read_confidence({"confidence": 0.0}) == 0.0

    def test_clamped(self) -> None:
        assert read_confidence({"confidence": 1.7}) == 1.0


class TestEffectiveConfidence:
    def test_missing_uses_when_missing(self) -> None:
        assert effective_confidence({}) == 1.0

    def test_zero_respected(self) -> None:
        assert effective_confidence({"confidence": 0.0}) == 0.0
```

Interaction with step 1: the fusion module already treats None as "do not penalize" - same convention. With H1 in place, a stored 0.0 reaches fusion as 0.0 and gets demoted correctly. Without H1, fusion is fed lies.

### H2. formula_version stamping at write (DONE - see 2026-06-11-prefix-confidence-hygiene-plan.md)

In the claim write path where confidence/credibility are computed (`services/context.py` ~1021-1026, the `props["confidence"] = ...` block), add:

```python
        props["confidence_formula_version"] = 1
```

No reader changes now. This exists so that when calibration lands (E1), old nodes are distinguishable from recalibrated ones without archaeology. One constant, one prop, zero risk.

### Explicitly NOT in the pre-fix (resist the itch)

- A1 kill-one-brain: days, touches everything step 1 touches. Post-benchmark, first item.
- E3 supersession canonical resolver: step 1 only SURFACES superseded_by; it does not need the resolver.
- D1 typed EpistemicState prop: a migration-shaped change; post-benchmark with A1.
- D2 link/CITE enum unification: a brain-cutover blocker, not a step-1 blocker.
- E8 decay knob unification: only one knob is live; dies naturally at cutover.

## Tier 2: PARALLEL TRACK (delegable, zero file overlap with step 1)

Safe to run as subagent work on the same branch while the founder executes step 1. None of these touch `context_query.py`, `quality.py`, `services/context.py`, `services/models.py`, or `settings.py`.

### P1. Doc truth-sync (docs only)

- `primitives/docs/06-epistemology.md`: corroboration section still documents naive `count(distinct source)`; CITE v2 shipped independence weighting (Phase 7). Sync the doc, note the naive count as the fallback. (Critique E5 - this is the doc gap on the exact mem0-#4573 mechanism we pitch against.)
- `primitives/docs/01-paradigm.md` or `02-layers.md`: one honest paragraph on the bimodal knowledge layer (structured triples from extraction; free-text claims from learn()) and which machinery applies to which (critique D4/E4).
- `context/architecture.md`: mark the SAGE/Dagster pipeline section as legacy-pending-cutover, add the reactive sage/transactions path, fix the "believe" verb reference (surface uses decide/accept). It currently documents only the dying brain.
- Layer-maturity note (critique E9): one table in architecture.md - Memory/Knowledge production-grade, Wisdom partial (synthesis weak, crystallize/revise legacy), Intelligence session-scoped storage.

### P2. Dead config cleanup (backlog already exists)

The 12 dead flags identified in the June dead-code audit (`backlog_dead_code_cleanup`). Pure deletion + test run. Touches settings.py - SEQUENCE AFTER step-1 Task 1 lands to avoid a merge conflict on the same file, or do it as the last parallel item.

### P3. Audit-tool groundwork (composes with sprint step 4)

The Memory Health Audit ingestion adapters (mem0 export JSON, markdown dirs) can be scaffolded against the custodian machinery without touching any read-path file. If parallel capacity exists, this beats P2 in value - it advances the Verda entry instrument.

## Tier 3: CONVERGENCE PLAN (the very next plan after the benchmark ships)

Priority order from the critique, recorded here so it survives the sprint:

1. Kill one brain (A1): finish the cutover blockers (link enum, crystallize signature, revise transaction), converge on sage/transactions as the only write path and one recall implementation, archive the legacy path. Fold in E8 (one per-layer decay config) and the sage-side confidence-default fixes.
2. One epistemic-state module (E2 done in pre-fix; extend): typed `EpistemicState` pydantic prop under a single key (D1), supersession canonical resolver with edge-as-truth (E3), conflict_status + resolution enums (E3), formula_version consumed by readers (E1). Placement decision (2026-06-11): the props-reading helpers (`engine/epistemics.py`) STAY in context-service - they interpret this service's storage format, not epistemology math, and no second consumer of that format exists. Only the conflict/resolution ENUMS move to primitives (they are format-independent epistemology vocabulary), and only when primitives next cuts a release anyway - do not cut a release for this alone.
3. Extraction over learn() writes (D4): async custodian extraction of free-text claims into SPO triples so agent writes join the structural contradiction/corroboration machinery. This widens exactly what the benchmark measures - schedule immediately after the benchmark so v2 of the number improves.
4. Ranking pipeline extraction (A2): one module, named stages, score-basis contract per consumer; absorb epistemic_fusion, thresholds, trust gate staging.
5. Settle ProposedBelief (E7): keep accept/dismiss adjudication (the differentiator), delete the confidence-threshold story, or the reverse - one commit, all surfaces.
6. Transaction-time (E6): add recorded_at alongside valid_from/valid_to before the audit positioning hardens; or formally scope the pitch to provenance/revision history.
7. Dual-write reconciliation job (A3): nightly Memgraph/Qdrant count + sample diff per silo; alert on drift. Also: document cache-layer TTLs as the erasure boundary for GDPR.
8. Hygiene: config flag rule (test-both-values or deletion date), multi-label Commitment -> subtype property (D3), edge taxonomy writer/consumer documentation (D2).

## Sequencing summary

```
Now      : H1 + H2 (half day, then straight into step-1 Task 0)
Parallel : P1 docs (subagent), P3 audit scaffold (subagent), P2 last
Mon gate : sprint steps 1-3 per the sprint plan (unchanged)
Next plan: Tier 3 items 1-3 first (kill brain, epistemic-state module, extraction-over-learn)
```

The discipline rule: if any Tier 3 item starts looking urgent before the benchmark ships, re-read finding #1 of the June 3 court verdict.
