# Devlog: v1-β6 Paradigm Completion

**Date:** 2026-04-29
**Branch:** `phase-eag-completion` (merged as PR #15)
**Status:** Complete

## Summary

Finished wiring the remaining `primitives.eag.epistemology` surfaces that v1-α left partially activated. This completes the paradigm integration work for v1-β.

## Changes

### Supersession structured path

`src/context_service/custodian/supersession.py` now uses two detection paths:

1. **Structured (SPO claims):** When nodes have `subject/predicate/object` fields, use `primitives.eag.epistemology.supersession.should_supersede()` for deterministic comparison based on confidence scores.
2. **LLM fallback:** Free-text nodes still use the existing LLM-based semantic comparison.

The structured path is preferred for reproducibility and speed. Added `detect_structured_supersession()` helper and `StructuredSupersessionPair` dataclass.

### Confidence wiring

`src/context_service/custodian/fact_promotion.py` now uses `combined_confidence(raw_confidence, source_tier)` from primitives instead of passing raw confidence through. This applies the source tier weighting (authoritative=1.0, verified=0.8, community=0.6, unknown=0.4) to the confidence score before promotion evaluation.

Added unit test verifying the formula matches primitives' implementation.

### Enum registry documentation

Created `context/architecture/enum-registries.md` documenting the deliberate split between:
- `extraction.models.RelationshipType` — LLM extraction vocabulary
- `primitives.schema.edges.CITEEdgeType` — graph edge registry

Decision: keep separate. Different lifecycles, different consumers, explicit mapping layer.

Closed EAG integration audit item #7.

## v1-β phase summary

| Phase | Description | PR | Status |
|-------|-------------|-----|--------|
| β0 | Review cleanup | #10 | Complete |
| β1 | Auth finish (per-request, silo ownership, WorkOS v6) | #11 | Complete |
| β2 | Dagster full (schedules, sensors, retry, poison queue) | #12 | Complete |
| β3 | SPLADE hybrid retrieval | #14 | Complete |
| β4 | Silo portability (export/import scripts) | #13 | Complete |
| β5 | Integration test pack | — | Deferred (covered by β3/β4 tests) |
| β6 | Paradigm completion | #15 | Complete |

## Deferred items

- **WorkOS real tenant verification** — needs production tenant access
- **Deprecated counter removal** — Q3 target per original plan
- **Validator refactor Phase C/D** — deferred until pydantic-ai breaks private API or 4th validation stage needed

## Next

v1-β feature work complete. Remaining work before v1.0:
- Production deploy validation
- Dagster concurrency pool tuning
- Poison queue dashboard/alerting
- Cost tracking integration (currently placeholder)
