# Plan: Validator Refactor — Finish Phase B

**Status:** Approved 2026-04-28
**Branch:** `phase-validator-b-finish`
**Workstream:** v1-α (close paradigm gaps)

## Goal

Finish the metric-label split that is the last open item from `validator-refactor.md` Phase B. Phase A is done (`custodian/rejection_reasons.py` ships all three enums); the validator + write_path use them correctly. The remaining gap is `metrics.py` still emits a single `_claim_rejections` counter, polluting per-layer dashboards.

## Current state (anchored from audit on 2026-04-28)

- `custodian/rejection_reasons.py` defines all three enums per `validator-refactor.md` § 3.3:
  - `StructuralRejection`: `SCHEMA_VIOLATION`, `INVALID_JSON`, `MISSING_FIELD`, `LOW_CONFIDENCE`
  - `CitationRejection`: `HALLUCINATED_NODE_ID`, `INVALID_CITATION`, `CROSS_TENANT`, `CROSS_SILO`, `NOT_CITED`
  - `BusinessRejection`: `LOW_CONFIDENCE`, `QUALITY_BELOW_THRESHOLD`, `ALL_CLAIMS_REJECTED`
- `validators.py:285, 295` uses `StructuralRejection` correctly.
- `business_rules.py::BusinessRuleValidator` exists; computes `quality_score(finding, cluster_size)` at line 88 and the all-claims-rejected check at lines 75-80.
- `write_path.py` uses the validator (`_default_business_validator` at line 54) but also computes its own quality score inline at line 335.
- `promotion.py:196-198` keeps the `min_quality` threshold gate. By design (per `business_rules.py:6` docstring): threshold is a caller arg, not validator logic.
- `metrics.py:62-65` defines a single `_claim_rejections` counter with `attributes={"reason": reason_str}`. Helper `record_claim_rejection(reason)` at line 149-154; `CustodianRejectionMetrics.increment_claim_rejection(reason)` at line 210-221.

## Tasks (priority order)

1. **Split the rejection counter into three counters in `metrics.py`.**
   - Replace the single `_claim_rejections` counter (line 62) with:
     - `custodian_structural_rejections{reason}` — labels from `StructuralRejection`
     - `custodian_citation_rejections{reason}` — labels from `CitationRejection`
     - `custodian_business_rejections{reason}` — labels from `BusinessRejection`
   - Keep the old counter as a deprecated alias for one release; emit to both. TODO comment with target removal date (2026-Q3).
   - Update `record_claim_rejection(reason)` (line 149) to dispatch by enum type.
   - Update `CustodianRejectionMetrics.increment_claim_rejection(reason)` (line 210) similarly.

2. **Verify call-sites need no change.**
   - Grep `validators.py` and `business_rules.py` for `record_claim_rejection` and `increment_claim_rejection`. If both go through the dispatcher, no edits needed.

3. **Update tests asserting on the metric label.**
   - Grep `tests/` for `custodian_claim_rejections`. Update each assertion to the new counter name matching the rejection enum used by the test fixture.

4. **Move quality-score computation into the validator (single source of truth).**
   - Per `validator-refactor.md` § 3.4: `BusinessRuleValidator` should own the quality score. Currently `business_rules.py:88` computes it; `write_path.py:335` *also* stores `qscore` from a separate computation.
   - Decision: validator's score is authoritative.
   - Edit `business_rules.py::evaluate` to set `quality_score` on the returned `StageResult`.
   - Edit `write_path.py` around line 335 to consume `result.quality_score` instead of re-computing.

5. **Audit `_pre_check_edge` for dead-code status (`validator-refactor.md` Q1).**
   - Grep for any code path that constructs `ProposedEdge` without `model_validate`. If none, add a comment: `# defensive: load-bearing only if a future raw-dict path bypasses Pydantic`. If a path exists, document it in the comment. No code change.

6. **Tests.**
   - Add `tests/test_metrics_split.py`: fire one rejection of each type, assert each lands on the correct counter.
   - Update existing custodian tests that asserted on the old counter name.

7. **Update `validator-refactor.md`.**
   - Mark Phase A and Phase B complete.
   - Mark Phase C (recovery migration) and Phase D (`ValidationPipeline`) explicitly deferred with reasons.

## Out of scope

- Phase C (`model_validator(mode='before')` + `result_retries` recovery migration). The monkey-patch in `output_recovery.py` works; migration risk is real. Defer.
- Phase D (`ValidationPipeline` abstraction). Optional per the original plan; defer until a concrete testability pain point.
- Moving the `min_quality` threshold out of `promotion.py`. Decision in `business_rules.py:6` docstring says it stays as a caller arg.
- Config-driven `quality.py` weights (`validator-refactor.md` Q3). Low priority.

## Done criteria

- Three named counters in `metrics.py`; old counter aliased + deprecated.
- `business_rules.py::evaluate` is the single source of the quality score; `write_path.py` consumes it.
- `_pre_check_edge` is documented (or removed if dead).
- All existing custodian tests pass; new metrics-split test passes.
- `just check` and `just test` pass.
- `validator-refactor.md` updated: A+B complete, C+D deferred.
