# SAGE Restructure Plan

Date: 2026-06-20
Status: Draft (reviewed 2026-06-21)
Related: [Coherence Layer v2](../specs/2026-06-18-coherence-layer-v2.md)

## Summary

Restructure SAGE from 4 agents (custodian, synthesizer, groundskeeper, validator) to 4 focused jobs (Promoter, Synthesizer, Decayer, Detector). Align with coherence-layer-v2 spec which shifts embedding to write-time and removes batch extraction.

## Current State

### Active SAGE Components

**Dagster Scheduled Jobs:**

| Component | Cadence | Assets |
|-----------|---------|--------|
| groundskeeper | hourly | heat, edge_heat, heat_diffusion, prewarm_sweep |
| validator | 5m | validator_contradiction, validator_stale_commitment, marker_cleanup |

**Taskiq Reaction Handlers (event-driven):**

| Reaction | Purpose |
|----------|---------|
| `COMPUTE_EMBEDDING` | Embed single node → Qdrant |
| `BATCH_COMPUTE_EMBEDDING` | Batch embed multiple nodes |
| `UPDATE_HEAT` | Increment heat score on access |
| `UPDATE_CLUSTER_MEMBERSHIP` | DEPRECATED (CITE v2), no-op |
| `CASCADE_STALENESS` | Propagate staleness to dependents |
| `FLAG_CONTRADICTION` | Mark conflict, queue consolidation |
| `CONSOLIDATE` | LLM-based conflict resolution |
| `CHECK_SYNTHESIS` | Trigger synthesis if cluster ready |
| `PROPAGATE_CONFIDENCE` | Incremental confidence diffusion |
| `CHECK_EXTRACTION_TRIGGER` | TX1: Extract claims from Memory |
| `TRACE_REASONING` | TX7: Persist hypotheses as chains |
| `CHECK_CONSENSUS` | TX6: Multi-agent consensus → Fact |
| `CHAIN_TOMBSTONED` | TX11: Cascade when chain dies |

Note: custodian and synthesizer Dagster schedules were disabled in Phase 9 — their work moved to Taskiq reactions.

### Maintenance Jobs (keep as-is)

- `daily_maintenance_schedule` — retention_sweep, tag_maintenance
- `groundskeeper_gc_schedule` — nightly Memory expiration
- `reasoning_compaction_schedule` — chain compaction
- `auto_tagging_schedule` — tag refinement
- `proposal_cleanup_schedule` — expired ProposedBelief cleanup
- `reconciliation_gc_schedule` — orphan recovery

## Target State

### SAGE "Dreaming" Jobs (all Dagster scheduled)

| Job | Cadence | Purpose | Source |
|-----|---------|---------|--------|
| Promoter | 5m | Claim → Fact when corroborated | custodian subset |
| Synthesizer | 15m | Facts → Belief when SUPPORTS threshold | synthesizer subset |
| Decayer | 1h | Memory confidence decay | new |
| Detector | 5m | SUPPORTS/CONTRADICTS edge creation | validator (renamed) |
| Observer | - | Intelligence layer passive tracking | Phase 2 |

**Latency note:** Detector runs every 5m, Synthesizer every 15m. Worst-case latency from new Facts to Belief synthesis is ~20m. This is acceptable — beliefs are not urgent.

### Taskiq Reactions (keep)

These stay as event-driven reactions:
- `COMPUTE_EMBEDDING` / `BATCH_COMPUTE_EMBEDDING` — embedding at write time
- `UPDATE_HEAT` — heat score on access
- `CASCADE_STALENESS` — staleness propagation
- `PROPAGATE_CONFIDENCE` — confidence diffusion
- `CHECK_CONSENSUS` — multi-agent consensus (TX6)
- `CHAIN_TOMBSTONED` — chain cascade (TX11)

### Taskiq Reactions (remove)

- `UPDATE_CLUSTER_MEMBERSHIP` — already no-op
- `CHECK_SYNTHESIS` — replaced by scheduled Synthesizer
- `FLAG_CONTRADICTION` / `CONSOLIDATE` — folded into Detector
- `CHECK_EXTRACTION_TRIGGER` — batch extraction removed; write-gate handles

### What Gets Removed

1. **Batch extraction** — write-gate embeds at write time
2. **Clustering** — MEMBER_OF edge removed; similarity-based synthesis instead
3. **Document → Entity extraction** — no Document or Entity nodes in new schema
4. **Chain stitching** — Intelligence layer deferred to Phase 2

### What Gets Consolidated

| Current | Target |
|---------|--------|
| custodian.claim_to_fact_promotion | Promoter |
| custodian.clustering + synthesizer.belief_synthesis | Synthesizer (cluster-free) |
| validator.contradiction + validator.stale_commitment | Detector |
| groundskeeper.heat_* | Keep separate (heat is scoring, not epistemology) |
| groundskeeper_gc (Memory deletion) | Decayer (confidence decay) + Groundskeeper (deletion) |

## Migration Plan

### Phase A: Decouple Embedding (prerequisite)

Write-gate must embed at write time before we can remove batch embedding from custodian.

**Current flow:**
```
Agent: learn(content, evidence) 
  → Store Claim (no embedding)
  → custodian picks up → embeds → stores embedding
```

**Target flow:**
```
Agent: learn(content, evidence)
  → Write-gate embeds synchronously
  → Store Claim + embedding
  → No custodian embedding step
```

**Tasks:**
1. Add embedding to write-gate pipeline (already partially there)
2. Verify all writes go through write-gate
3. Remove embedding from custodian reaction worker
4. Add migration for unembedded legacy nodes

### Phase B: Introduce Promoter

Extract claim→fact promotion from custodian into dedicated Promoter job.

**Promotion criteria (from spec):**
```python
def should_promote(claim: Claim) -> bool:
    similar = find_similar_claims(claim, threshold=0.85)
    if len(similar) >= 2:
        return True  # corroboration
    if claim.evidence_hash and verify_evidence(claim):
        return True  # evidence verified
    if claim.confidence >= 0.9 and claim.metadata.get("source_tier") == "authoritative":
        return True  # trusted source
    return False
```

**Tasks:**
1. Create `sage_promoter_job` (Dagster, 5m)
2. Query: claims without `promoted=true` and confidence > threshold
3. Run promotion check
4. Create Fact node + DERIVED_FROM edge to Claim
5. Remove promotion logic from custodian Taskiq worker

### Phase C: Simplify Synthesizer

Remove cluster-based synthesis. Use similarity search instead.

**Current:** Cluster nodes via MEMBER_OF → synthesize when cluster reaches threshold
**Target:** Find semantically similar Facts → synthesize when count >= 3 and mutually supporting

**Tasks:**
1. Remove MEMBER_OF edge creation
2. Remove clustering assets from synthesizer
3. Update synthesis to use vector similarity
4. Adjust cadence from reaction-based to scheduled (15m)

### Phase D: Introduce Decayer

New job for Memory confidence decay. Currently groundskeeper_gc only deletes; it doesn't decay.

**Decay formula:**
```python
def decay_confidence(memory: Memory, hours_since_access: float) -> float:
    return memory.confidence * (memory.decay_rate ** hours_since_access)
```

**Tasks:**
1. Create `sage_decayer_job` (Dagster, 1h)
2. Query: Memory nodes with `last_accessed_at` > 1h ago
3. Apply decay formula, update confidence
4. Keep groundskeeper_gc for deletion (confidence < threshold)

### Phase E: Rename Validator → Detector

Cosmetic rename + consolidate contradiction/support detection.

**Tasks:**
1. Rename `sage_validator_schedule` → `sage_detector_schedule`
2. Rename assets: `validator_contradiction` → `detect_contradicts`
3. Add `detect_supports` asset (currently missing - only contradictions detected)
4. Keep stale_commitment detection (still relevant for Commitments)
5. Keep marker_cleanup

### Phase F: Prune Custodian/Synthesizer

After Phases A-E, custodian and synthesizer Taskiq workers should be empty.

**Tasks:**
1. Verify no remaining work in custodian worker
2. Verify no remaining work in synthesizer worker
3. Delete Taskiq worker code
4. Update docs to reflect new structure

## Dependency Graph

```
Phase A (write-gate embedding)
    ↓
Phase B (Promoter) ─────────────────────┐
    ↓                                   │
Phase C (Synthesizer simplify)          │
    ↓                                   │
    ├── 2+ weeks stable ────────────────┤
    ↓                                   │
Phase F (prune custodian/synthesizer) ←─┘
                                        
Phase D (Decayer) ← independent
Phase E (Detector rename) ← independent
```

Phases D and E can happen in parallel with A-C.

**Critical gate:** Phase F blocked until Phase A feature flag removed and write-gate embedding stable for 2+ weeks. This ensures rollback path remains viable.

## Rollback Strategy

Each phase is deployable independently:
- **Phase A:** Feature flag `WRITE_GATE_EMBED=true`. Rollback = set false, custodian re-embeds.
- **Phase B:** Promoter runs alongside custodian promotion. Rollback = disable Promoter, custodian continues.
- **Phase C:** Schema migration for MEMBER_OF removal. **Forward-only** — clustering data not recoverable once edges deleted. Keep edges in `deprecated` state if rollback needed.
- **Phase D:** Decayer is additive. Rollback = disable job.
- **Phase E:** Rename only. Rollback = rename back.
- **Phase F:** **Blocked until** `WRITE_GATE_EMBED` flag removed and write-gate embedding stable for 2+ weeks in prod. Cannot rollback Phase A if custodian code deleted.

## Timeline Estimate

| Phase | Effort | Notes |
|-------|--------|-------|
| A | 2-3 days | Write-gate changes + migration |
| B | 1 day | Extract existing logic |
| C | 2 days | Schema migration + vector-based synthesis |
| D | 0.5 day | New job, simple logic |
| E | 0.5 day | Renames |
| F | 1-1.5 days | Cleanup + test migration |

**Total:** ~8-9 days realistic, can be parallelized to ~6 days

Phase A is highest risk (50ms budget with TEI is tight). Add buffer for edge cases in legacy node migration.

## Design Decisions

### Write-gate Embedding
- Sync embed for single writes (fits 50ms budget)
- Bulk imports (>10 nodes): queue for batch embedding, return immediately with `embedding_pending=true`
- Threshold configurable via `silo_config.batch_embed_threshold` (default 10, min 1, max 1000)
- Custodian batch path remains for bulk/migration scenarios

### Cluster-free Synthesis
- Detector creates SUPPORTS edges first (async, LLM-based)
- Synthesizer queries: "3+ Facts with SUPPORTS edges between them" → Belief
- **Triangle required:** 3 facts need 3 direct edges (A↔B, B↔C, A↔C) — no transitive chains
- Removes MEMBER_OF edge and Cluster node entirely

### Decayer Parameters
- `decay_rate = 0.98` default (~82% after 10 hours, ~37% after 50 hours)
- Update `last_accessed_at` on recall hit and tick
- Delete when `confidence < 0.05` (existing GC, lower threshold)
- Per-node `decay_rate` override via metadata (preferences decay slower)
- **Cache note:** Recall cache hits don't update `last_accessed_at`. This is acceptable — decay is approximate, not precise. Cache TTL ensures eventual cache-miss.

### SUPPORTS Detection
- Cosine similarity > 0.85 + LLM confirmation "do these say the same thing?"
- SUPPORTS is symmetric for same-layer nodes
- DERIVED_FROM handles cross-layer relationships (Memory→Claim→Fact)
- No transitivity: A supports B, B supports C does NOT create A→C

### ProposedBelief Flow
- Keep ProposedBelief for agent oversight
- Add silo config: `auto_accept_beliefs: bool = false`
- Default: agent must accept. Opt-in: auto-promote to Belief.

### Runtime Model (all Dagster scheduled)

| Job | Cadence | Rationale |
|-----|---------|-----------|
| Promoter | 5m | Match spec, simpler ops than Taskiq |
| Synthesizer | 15m | Beliefs can wait, batch efficient |
| Decayer | 1h | Decay is gradual, no urgency |
| Detector | 5m | Edge creation can batch |

All jobs on Dagster for operational simplicity. Taskiq reactions kept only for: embedding, heat, consensus, confidence propagation, chain tombstone cascade.

### Heat Scoring
- Keep as separate groundskeeper concern
- Heat is engagement scoring, Detector is epistemology
- No change to existing heat/diffusion logic
- `prewarm_sweep` stays with groundskeeper (cache warming, not epistemology)

### Out of Scope

- **Tool surface reduction** (25→5 tools): Tracked separately per coherence-layer-v2 spec. Includes `decide` deprecation.
- **Intelligence layer** (Observer job): Phase 2, after benchmark validation.

## Open Questions

1. **Intelligence layer trigger** — After benchmark validation, before v1.0?

2. **Bulk import threshold** — Default 10 reasonable? Could tune per-silo based on usage patterns.
