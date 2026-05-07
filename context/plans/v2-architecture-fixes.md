# Plan: v2 Architecture Fixes

**Branch**: `phase-v2-architecture-fixes`
**Spec**: `context/specs/v2-architecture-fixes.md`
**Status**: Ready

## Goal

Align implementation with EAG spec, eliminate reliability risks, improve tool ergonomics, and ship system-initiated belief synthesis as strategic differentiator.

## Scope

- P0: Philosophy gaps (promotion, confidence, T3/T7)
- P1: Infrastructure (outbox, raw Cypher, hydration)
- P2: Tool surface refactor
- P3: Minor fixes (timestamps, valid_to)
- NEW: ProposedBelief flow

## Out of Scope

- Event sourcing
- LLM-based conflict detection
- Backward compatibility (not public yet)

---

## Batch 1: Philosophy Fixes

Non-breaking. Can merge to main incrementally.

### Task 1.1: Async R1 Promotion Status
- [ ] Delete auto-promote block in `mcp/tools/context_store.py` (lines 188-203)
- [ ] Add `status: "pending_promotion"` to knowledge layer response
- [ ] Update tool docstring
- [ ] Test: knowledge write returns pending status

### Task 1.2: Two-Phase Confidence
- [ ] Add `partial_confidence` function to `primitives.eag.epistemology.confidence`
- [ ] Wire in `services/context.py::assert_claim`
- [ ] Store both `raw_confidence` and `partial_confidence` on Claim
- [ ] Update `custodian/fact_promotion.py` to compute `final_confidence` with corroboration
- [ ] Store `final_confidence` on Fact node
- [ ] Backfill asset: set `partial_confidence = raw_confidence * 0.7` for existing Claims
- [ ] Test: confidence values are calibrated

### Task 1.3: T3/T7 Kind Field
- [ ] Add `kind` param to `CREATE_COMMITMENT` in `db/queries.py`
- [ ] Add `kind` param to wisdom branch in `context_store.py`
- [ ] Set `kind = "pattern"` in `custodian/consensus_promotion.py` for T3 path
- [ ] Backfill asset: infer kind from edges (SYNTHESIZED_FROM → pattern, DECLARED_BY → rule, else unknown)
- [ ] Test: new commitments have kind, backfill works

### Task 1.4: Timestamp Parameterization
- [ ] Update `PROMOTE_CLAIM_TO_FACT` to use `$promoted_at`, `$valid_from` params
- [ ] Update caller in `fact_promotion.py`
- [ ] Test: timestamps are parameterized

### Task 1.5: Commitment valid_to on Finding
- [ ] Update `CREATE_FINDING_FROM_COMMITMENT` to set `cm.valid_to = $promoted_at`
- [ ] Test: promoted Commitments have valid_to set

**Done when**: All tests pass, `just check` clean, PR merged.

---

## Batch 2: Infrastructure

Non-breaking. Requires Batch 1 merged.

### Task 2.1: Outbox Pattern
- [ ] Create `engine/outbox.py` with `OutboxWriter`, `OutboxPoller`
- [ ] Implement 3x retry on Redis LPUSH
- [ ] Create `pipelines/sensors/outbox_embed_sensor.py`
- [ ] Create `pipelines/jobs/outbox_embed_job.py`
- [ ] Update `services/context.py::store()` to use outbox
- [ ] Remove inline Qdrant write + rollback (lines 315-336)
- [ ] Add metrics: `outbox_queue_depth`, `outbox_processing_latency_p95`
- [ ] Configure DLQ alert (depth > 0 for > 5 min)
- [ ] Test: writes work, outbox drains, DLQ catches failures
- [ ] Document rollback procedure

### Task 2.2: Raw Cypher Mixin
- [ ] Create `engine/raw_cypher.py` with `RawCypherMixin`
- [ ] Move `execute_query`, `execute_write`, `session`, `transaction` to mixin
- [ ] Update `MemgraphStore` to inherit from both `HyperGraphStore` and `RawCypherMixin`
- [ ] Remove methods from `HyperGraphStore` protocol
- [ ] Grep callers, update imports
- [ ] Test: existing functionality works

### Task 2.3: Hydration Registry
- [ ] Create `engine/hydration.py` with registry pattern
- [ ] Register hydrators for Document, Passage, Claim, Fact, Commitment, etc.
- [ ] Replace `_node_from_record` in `memgraph_store.py` with `hydrate_node`
- [ ] Test: node hydration works for all types

**Done when**: Outbox processing verified in staging, metrics visible, PR merged.

---

## Batch 3: Tool Surface + ProposedBelief

Requires Batch 2 stable.

### Task 3.1: Belief Accept/Reject Tools
- [ ] Create `mcp/tools/context_accept_belief.py`
- [ ] Create `mcp/tools/context_reject_belief.py`
- [ ] Register in `mcp/server.py`
- [ ] Test: accept converts ProposedBelief to WorkingBelief, reject marks rejected

### Task 3.2: ProposedBelief Node + Queries
- [ ] Add ProposedBelief schema to `db/queries.py`
- [ ] Add indexes for ProposedBelief (silo_id, status)
- [ ] Create queries: CREATE_PROPOSED_BELIEF, GET_PROPOSED_BELIEFS, UPDATE_PROPOSED_BELIEF_STATUS
- [ ] Test: CRUD works

### Task 3.3: Belief Synthesis Sensor
- [ ] Create `pipelines/sensors/belief_synthesis_sensor.py`
- [ ] Implement memory clustering logic (spike first — reuse clustering/service.py?)
- [ ] Propose belief if cluster size >= 5, confidence >= 0.7
- [ ] Rate limit: max 3 proposals per silo per hour
- [ ] Test: sensor proposes beliefs from memory clusters

### Task 3.4: Surface Proposals in context_recall
- [ ] Update `context_recall` to query ProposedBelief nodes
- [ ] Add `proposed_beliefs` array to response
- [ ] Include evidence_ids for transparency
- [ ] Test: recall returns proposals

### Task 3.5: Improve context_store UX
- [ ] Improve error messages for missing required params per layer
- [ ] Add concrete examples to docstring
- [ ] Test: clear errors on bad input

### Task 3.6: Restructure context_admin
- [ ] Replace `ref`/`name` with explicit `node_id`/`chain_id`/`session_id`
- [ ] Update all action handlers
- [ ] Test: all admin actions work
- [ ] Test: all admin actions work with new params

### Task 3.8: Error UX Standard
- [ ] Implement consistent error envelope across all tools
- [ ] Add `ignored_flags` to responses where applicable
- [ ] Test: errors are consistent, ignored flags surfaced

### Task 3.9: Update Documentation
- [ ] Update `CLAUDE.md` — new tool surface (12 tools)
- [ ] Update `context/api-examples.md` — new tool examples
- [ ] Update `../primitives/context/specs/` if epistemology changes landed
- [ ] Update Notion wiki — tool reference, architecture diagrams
- [ ] Update `context/plans/README.md` — mark v2 shipped

**Done when**: All new tools work, `context_store` deleted, docs updated.

---

## Verification

After each batch:
- [ ] `just check` passes
- [ ] `just test` passes
- [ ] `just test-integration` passes (if stack available)
- [ ] Manual smoke test on strata-finance devbox

---

## Rollback Procedures

### Batch 1
Revert PR. No data migration issues.

### Batch 2 (Outbox)
1. Revert `services/context.py` to inline Qdrant writes
2. Keep outbox sensor running to drain existing queue
3. Investigate, fix, redeploy

### Batch 3
1. Re-enable `context_store` (remove deprecation)
2. Keep new tools available (additive)
3. Coordinate with strata-finance on timeline

---

## Dependencies

- Batch 2 requires Batch 1 merged
- Batch 3 requires Batch 2 stable (outbox working in prod)
- **Task 1.2**: Requires `partial_confidence` function in `primitives.eag.epistemology.confidence` — cross-repo change, confirm exists before starting
- **Task 3.4**: Requires spike to determine whether to reuse `clustering/service.py` or implement standalone (1-day timebox)

## Pre-Batch Checkpoints

- [ ] Confirm `partial_confidence` exists in primitives (before Batch 1)
- [ ] Spike: clustering approach for belief synthesis (before Batch 3)
- [ ] Run backfill assets against staging snapshot, verify counts (before each prod backfill)

---

## Estimates

| Batch | Effort | Risk |
|-------|--------|------|
| Batch 1 | S-M | Low |
| Batch 2 | M | Medium (outbox is new infra) |
| Batch 3 | M-L | Medium (breaking change) |

Total: ~2-3 weeks with focused effort.

---

## Done Criteria

- [ ] Knowledge writes return `pending_promotion`
- [ ] Confidence is two-phase calibrated
- [ ] Commitments have `kind` field
- [ ] Outbox handles all Qdrant writes
- [ ] Raw Cypher isolated to mixin
- [ ] Hydration uses registry
- [ ] `context_accept_belief` + `context_reject_belief` live
- [ ] ProposedBelief flow working
- [ ] `context_recall` surfaces proposals
- [ ] `context_store` has improved error UX
- [ ] `context_admin` params restructured
- [ ] Docs updated
- [ ] All tests pass

---

## Follow-up (separate plan)

**MCP Tool Observability** — track usage patterns to inform future tool surface:
- Tool call frequency
- Param usage/ignored patterns
- Error rates, latency by tool
- Agent behavior patterns

Plan separately after v2 ships. Data-driven tool surface decisions.
