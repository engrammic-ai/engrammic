# Plan: Notion Docs Update (Post-v2)

**Priority**: P3 chore
**Status**: Blocked on v2 ship
**Estimate**: S (2-4 hours)
**Prerequisite**: Batch 3 of `v2-architecture-fixes` merged and stable

Do this after `phase-v2-architecture-fixes` is fully merged to main.

---

## Scope

Pages on the Notion wiki that will be stale after v2 ships:

- Tool reference page (7 tools → 9 tools, param changes)
- Architecture overview / cognitive layers diagram
- Developer quickstart / usage examples
- Any page referencing `context_store` error behavior or `context_admin` params

---

## Checklist

### Tool reference

- [ ] Add `context_accept_belief` — accepts a ProposedBelief, converts to WorkingBelief
- [ ] Add `context_reject_belief` — rejects a ProposedBelief
- [ ] Update `context_recall` — document new `proposed_beliefs` array in response
- [ ] Update `context_store` — document improved error messages; remove mention of auto-promotion for knowledge layer; note `status: "pending_promotion"` in knowledge layer response
- [ ] Update `context_admin` — replace `ref`/`name` params with `node_id`/`chain_id`/`session_id`

### Architecture / concepts

- [ ] Belief lifecycle diagram — add ProposedBelief state between memory clustering and WorkingBelief
- [ ] Confidence section — update to reflect two-phase model: `raw_confidence` → `partial_confidence` at store time, `final_confidence` at promotion (with corroboration)
- [ ] Commitment section — note `kind` field on T3/T7 nodes (`pattern`, `rule`, `unknown`)
- [ ] Outbox note — if we have an ops/infrastructure page, add note that Qdrant writes are async via outbox (not inline)

### Usage examples

- [ ] Update any code snippets that call `context_admin` with old `ref`/`name` params
- [ ] Add example showing `context_recall` response with `proposed_beliefs`
- [ ] Add accept/reject belief workflow example

---

## Notes

- Task 3.9 in the v2 plan covers the in-repo docs (`CLAUDE.md`, `context/api-examples.md`); this plan covers only the external Notion wiki
- No schema migrations are user-facing; no separate migration note needed
- If Notion pages have embedded architecture diagrams, flag for Vic to update visuals
