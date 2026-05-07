# Brainstorm: P0-P2 Architecture Fixes

**Date**: 2026-05-07
**Mode**: Architecture (5 parallel agents)

## Summary

The philosophy gaps (P0) are smaller than expected - most infrastructure exists, just needs wiring. The dual-write fix (P1) needs new components but is well-understood. Tool ergonomics (P2) is the largest surface area change but can ship non-breaking via deprecation shim.

## Decisions

| Issue | Winner | Rationale |
|-------|--------|-----------|
| R1 promotion | All async via Custodian | Spec-compliant; infrastructure exists |
| Confidence formula | Wire at promotion time | Already correct placement |
| T3/T7 distinction | `kind` field on `:Commitment` | Simpler than separate labels |
| Dual-write | Outbox pattern | At-least-once, no new infra |
| Tool surface | Parallel period + deprecate | MCP client already deployed |

## Implementation Plan

### Batch 1: Quick Wins (1 PR)

**P0-3: T3/T7 `kind` field**
- Add `kind: Literal["rule", "pattern"]` to Commitment nodes
- Files: `context_store.py`, `services/context.py`, `db/queries.py`, `consensus_promotion.py`
- New: `pipelines/assets/migrate_commitment_kind.py` (backfill existing)
- Effort: S

**P0-1: R1 promotion status**
- Return `{"status": "pending_promotion", "claim_id": "..."}` on knowledge writes
- Delete auto-promote code (lines 188-203 in `context_store.py`)
- Effort: S

**P0-2: Confidence formula**
- Wire `primitives.eag.epistemology.confidence.combined_confidence` in `services/context.py::assert_claim`
- ~5 lines change
- Effort: S

### Batch 2: Dual-Write Outbox (1 PR)

**P1: Outbox pattern**
```
MCP write
    |
    v
Memgraph (sync) + Redis outbox (sync)
    |
    return node_id immediately
    .
    . (async)
    .
OutboxEmbedSensor (Dagster)
    |
    embed content -> Qdrant upsert
    |
    mark done / dead-letter after 3 attempts
```

- Remove inline rollback (lines 315-336 in `services/context.py`)
- New: `engine/outbox.py` (OutboxWriter, OutboxPoller)
- New: `pipelines/sensors/outbox_embed_sensor.py`
- Effort: M

### Batch 3: Tool Ergonomics (1 PR, breaking)

**New tool surface (8 tools)**

Writes:
- `context_remember(content, tags?, decay_class?)` - memory
- `context_assert(content, evidence, source_type)` - knowledge (evidence REQUIRED)
- `context_commit(about, reasoning)` - wisdom
- `context_reason(conclusion, steps)` - intelligence

Keep as-is:
- `context_recall` - unified reads
- `context_link` - relationships
- `context_belief_state` - session beliefs
- `context_update_belief` - mutate belief
- `context_crystallize` - promote to commitment

Restructure:
- `context_admin` - drop ref/name collision, use explicit `node_id`/`chain_id`/`session_id`

**Migration path**
1. Phase 1: Add 4 new write tools as thin wrappers. `context_store` stays live.
2. Phase 2: Deprecate `context_store` (log warning, docstring notice). 2 sprint cycles.
3. Phase 3: Remove `context_store`.

**Error UX standard**
```json
{
  "error": "missing_required_param",
  "param": "evidence",
  "tool": "context_assert",
  "message": "evidence is required for context_assert",
  "ignored_flags": ["decay_class"]
}
```

**Docstring format**
1. When to use (1 sentence)
2. Required vs optional (explicit list)
3. One concrete example with confidence calibration guidance

## Dependency Graph

```
Batch 1 (independent)
├── T3/T7 kind field
├── R1 pending_promotion status
└── Confidence formula wiring

Batch 2 (independent of Batch 1)
└── Outbox pattern

Batch 3 (after Batches 1+2 stable)
└── Tool surface refactor
```

Batches 1 and 2 can run in parallel. Batch 3 waits for stability.

## Open Questions

1. Should `context_remember` support `decay_class` or is that over-engineering?
2. Dead-letter alert threshold: 3 attempts? 5?
3. Deprecation period: 2 sprints or until strata-finance migrates?

## Not Doing

- Event sourcing for dual-write (overkill, no event log exists)
- Separate `:Belief` vs `:Commitment` labels (kind field sufficient)
- Sync semantic conflict detection (blows 30ms budget)
- LLM-based confidence calibration (formula is sufficient)
