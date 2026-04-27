# Plan: EAG `:Claim` → `:Fact` Promotion Path

**Status:** Approved 2026-04-28
**Branch:** `phase-eag-a-claim-fact-promotion`
**Workstream:** v1-α (close paradigm gaps)

## Goal

Add the canonical EAG Knowledge-layer write path. `:Claim` nodes promote to `:Fact` when `primitives.eag.epistemology.promotion.should_promote_r1` / `should_promote_r2` returns a positive decision. `:Finding` (RAG-era cluster/silo synthesis output) keeps its current semantics — it is **not** renamed or merged.

## Why this option

Renaming `:Finding` → `:Fact` requires a non-trivial data migration of live custodian output and offers no new capability. Adding `:Claim` → `:Fact` promotion as a parallel path activates `primitives.eag.epistemology` (which the paradigm doc says drives the layer transition), uses indexes that already exist (`db/indexes.py:54-56`), and leaves the working RAG-era pipeline alone.

## Current state (anchored from audit on 2026-04-28)

- `services/context.py::assert_claim` (line 555-609) writes `:Claim` only (`node_type="Claim"` at line 594).
- `consensus_promotion.py` writes `:Finding` from `:Claim:Commitment`. Cypher in `engine/queries.py` around line 1070.
- `:Fact` is indexed in `db/indexes.py:54-56`. No code path writes `:Fact`.
- `primitives.eag.epistemology.promotion` exports `should_promote_r1`, `should_promote_r2`, `ClaimForPromotion`, `PromotionDecision`. Currently unused in this repo.
- EAG read tools (`context_query`, `context_get`, `context_graph`) filter by the `layer` *property*, not by node label, so `:Finding` and a future `:Claim:Fact` both pass `layer="knowledge"` filters (`services/context.py:750-752`).

## Tasks (priority order)

1. **Document the `:Finding` vs `:Fact` semantic split.**
   - Edit `architecture/README.md` (create if missing). One section: `:Finding` = cluster/silo synthesis (RAG-era, active); `:Fact` = EAG-promoted Knowledge from a single `:Claim` (R1/R2 promotion).
   - Update `eag-integration-audit.md`: replace open-question #5 (Finding vs Fact) with a pointer to the new architecture note.

2. **New module `custodian/fact_promotion.py`.**
   - Imports `should_promote_r1`, `should_promote_r2`, `ClaimForPromotion`, `PromotionDecision` from `primitives.eag.epistemology.promotion`.
   - One pure function: `evaluate_claim_for_fact(claim_props, evidence_count, corroborations) -> PromotionDecision`. Adapter only — no DB access.
   - Distinct from `consensus_promotion.py` (Claim:Commitment → Finding). Keep the modules separate.

3. **Cypher: `PROMOTE_CLAIM_TO_FACT` in `db/queries.py`.**
   ```cypher
   MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
   WHERE NOT c:Fact
   SET c:Fact, c.promoted_at = datetime(), c.promotion_rule = $rule
   RETURN c
   ```
   - Multi-label set (not node copy) preserves all existing edges.
   - Index hit: `:Claim(silo_id, id)` already exists.

4. **`services/context.py::promote_claim_to_fact(silo_id, claim_id, rule)`.**
   - Reads claim props + evidence count via existing `MemgraphStore` methods.
   - Calls `evaluate_claim_for_fact`. If decision is positive, runs `PROMOTE_CLAIM_TO_FACT`.

5. **Wire `context_assert` to trigger promotion when threshold met.**
   - Edit `mcp/tools/context_assert.py`: when `len(evidence) >= R1_THRESHOLD` (configurable, primitives default), call `promote_claim_to_fact` after the `:Claim` write. Best-effort — promotion failure does not fail the assert.
   - Do not add a new MCP tool. Promotion is a side-effect, not an agent verb.

6. **Dagster asset stub for batch R2 promotion.**
   - File: `pipelines/assets/fact_promotion.py`. Scans `:Claim` nodes per silo, evaluates R2 (corroboration-based), runs `PROMOTE_CLAIM_TO_FACT` for positives.
   - Wire into `pipelines/definitions.py`. Not scheduled in v1-α; shipped as an asset only.

7. **Tests.**
   - `tests/test_fact_promotion.py` — unit tests for `evaluate_claim_for_fact` (R1, R2, rejection paths). Pure-function, no DB.
   - `tests/integration/test_assert_to_fact.py` (marker `integration`): assert a claim with 3 evidence items, verify the node carries both `:Claim` and `:Fact` labels.

## Out of scope

- Renaming or migrating `:Finding`. Custodian output stays as-is.
- Wiring `primitives.eag.epistemology.supersession` and `.confidence` — separate plans.
- Retroactive bulk promotion of existing `:Claim` nodes.

## Done criteria

- `:Claim` nodes with sufficient evidence carry the `:Fact` label after `context_assert`.
- `primitives.eag.epistemology.promotion` is imported and used in production code.
- `architecture/README.md` documents the `:Finding`/`:Fact` semantic split.
- `just check` and `just test` pass; integration test passes against the docker stack.
- `eag-integration-audit.md` open-question #5 is closed.
