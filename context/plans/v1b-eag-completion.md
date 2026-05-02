# Plan: Paradigm Completion + Hygiene

**Status:** Complete 2026-05-02 (verified by audit). One item deferred: deprecated claim_rejections counter removal, Q3 target, replacement counters already live.
**Branch:** `phase-eag-completion`
**Workstream:** v1-β phase 6 (opportunistic; pick items off as time allows)

## Goal

Finish exercising the primitives epistemology surface that v1-α only partially activated, schedule the fact-promotion asset, and clear the small backlog of hygiene items that have accumulated.

## Why

`primitives.eag.epistemology` has three modules — `promotion`, `supersession`, `confidence`. v1-α wired only `promotion`. The other two have callers in primitives' `lifecycle.py` but no use in this repo, despite custodian/supersession.py implementing supersession via free-text LLM calls (which the structured pure-function path can replace for many cases). The hygiene backlog is small but worth flushing before v1.0 planning starts.

## Current state (anchored from audit on 2026-04-28)

- `primitives.eag.epistemology.supersession` exposes `should_supersede(old: ClaimForSupersession, new: ClaimForSupersession) -> SupersessionDecision` and `detect_contradiction`. Both pure functions.
- `primitives.eag.epistemology.confidence` exposes confidence aggregation (combined_confidence calculation) and `SourceTier`.
- `src/context_service/custodian/supersession.py` uses an LLM call for supersession detection (free-text content nodes).
- `src/context_service/custodian/fact_promotion.py` already wires `promotion` (v1-α).
- `src/context_service/pipelines/assets/fact_promotion.py` exists but is **not** wired into a `ScheduleDefinition` in `pipelines/definitions.py`.
- `src/context_service/auth/workos_client.py:30-35` — TODO to verify `authenticate_with_session_token` against a real tenant.
- `src/context_service/custodian/metrics.py:67-70` — `_claim_rejections` deprecated counter alias with `TODO(2026-Q3)` removal target.
- `src/context_service/extraction/models.py::RelationshipType` and `primitives.schema.edges.CITEEdgeType` overlap on `CAUSES`. Audit item #7.

## Tasks

### Paradigm completion

1. **Wire `primitives.eag.epistemology.supersession`.**
   - Edit `src/context_service/custodian/supersession.py`. Add a structured-path helper that converts two `:Claim` (or `:Fact`) nodes' properties into `ClaimForSupersession` and calls `should_supersede`.
   - Use the structured path when both claims have machine-readable comparable fields (subject/predicate/object — the SPO claim shape from `models/mcp.py::SPOClaim`). Fall back to the LLM path for free-text-only cases.
   - The decision is "structured path replaces LLM where applicable, doesn't replace LLM entirely." Document the dispatch logic in a module docstring.

2. **Wire `primitives.eag.epistemology.confidence`.**
   - Edit `src/context_service/services/context.py::promote_claim_to_fact` and the Dagster `claim_to_fact_promotion` asset. When a claim accumulates evidence from multiple sources, use `combined_confidence` to aggregate rather than the simpler heuristic in the current code.
   - Add a unit test that verifies confidence aggregation matches primitives' formula.

3. **Schedule `claim_to_fact_promotion` Dagster asset.**
   - Edit `src/context_service/pipelines/definitions.py`. Add a `ScheduleDefinition` (e.g. `@schedule(cron_schedule="0 * * * *", job=fact_promotion_job)` for hourly per silo) wrapping the asset.
   - Coordinates with β2c — if β2c has already wired the schedule, this task is just a verification that it lands cleanly.

### Hygiene

4. **Verify WorkOS SDK against real tenant.** Final confirmation of `authenticate_with_session_token` (or whatever the verified method is). Pin SDK version in `pyproject.toml`. Update integration test `tests/integration/test_auth_workos.py` mock signature if the verified path differs from the placeholder.

5. **Remove deprecated `custodian.claim_rejections` counter alias.**
   - Triggered by 2026-Q3 (or sooner if dashboards have migrated).
   - Verify dashboards use the new layer-specific counters (`structural_rejections`, `citation_rejections`, `business_rejections`). If any still reference the old counter, migrate them first.
   - Edit `metrics.py`: remove the `_claim_rejections` counter, the dual-emit calls in `record_claim_rejection` and `CustodianRejectionMetrics.increment_claim_rejection`, and the TODO comment.
   - Update any tests asserting on the old counter name.

6. **`RelationshipType.CAUSES` ↔ `CITEEdgeType.CAUSES` alignment.**
   - Audit item #7 from `eag-integration-audit.md`.
   - Decide: is the extraction pipeline expected to write EAG semantic edges directly?
   - If **yes**: replace `extraction/models.py::RelationshipType` with `CITEEdgeType` from primitives. Migrate any existing call sites. Update tests.
   - If **no** (the extraction vocabulary intentionally differs from the EAG edge registry): document the deliberate split in `architecture/README.md` and close the audit item.
   - Default recommendation: **document the split**. The two enums serve different purposes (LLM extraction vocabulary vs graph edge type registry) and merging them would entangle extraction surface with paradigm contracts.

### Hygiene (deferred — listed for completeness)

7. **Validator refactor Phase C** (recovery monkey-patch → pydantic-ai `result_retries`). Defer unless pydantic-ai breaks the private API. The `output_recovery.py` patch works in production today.

8. **Validator refactor Phase D** (`ValidationPipeline` abstraction). Defer until adding a 4th validation stage. Optional per the original `validator-refactor.md` plan.

## Out of scope

- Full LLM replacement for supersession (the structured path complements the LLM path; doesn't replace it).
- Configurable confidence-aggregation formulas (use primitives' default; reconsider if A/B testing emerges as a need).
- Validator refactor Phase C/D actual implementation (deferred).

## Done criteria

- `primitives.eag.epistemology.supersession` and `.confidence` both have at least one production caller.
- `claim_to_fact_promotion` runs on a schedule, not just on `assert_claim`.
- WorkOS path verified against real tenant; SDK version pinned.
- `custodian.claim_rejections` counter removed when 2026-Q3 hits (or sooner if dashboards migrated).
- `RelationshipType.CAUSES` decision documented.
- Audit doc fully closed (`context/plans/eag-integration-audit.md` "Needs discussion" section either resolved or marked as v1.0+).
- `just check` and `just test` green.
