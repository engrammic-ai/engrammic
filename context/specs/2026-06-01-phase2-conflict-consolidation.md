# Phase 2: Conflict Detection + Consolidation

**Status:** Approved  
**Date:** 2026-06-01  
**Branch:** `feat/brain-architecture`

## Overview

Phase 2 implements conflict detection at write time, consolidation infrastructure, atomic corroboration checking, and static credibility scoring. This replaces batch-based SAGE conflict detection with reactive, write-time enforcement.

### What Phase 2 Delivers

- Conflict detection at write time (TX2 STORE_CLAIM)
- Bidirectional CONTRADICTS edges with `conflict_status` tracking
- Consolidation infrastructure (queue + worker + deterministic resolver)
- Atomic CHECK_CORROBORATION helper (fixes Phase 1 placeholder)
- Static credibility formula with transparency breakdown

### Not In Phase 2

| Item | Deferred To | Rationale |
|------|-------------|-----------|
| LLM subagent consolidation | Phase 7 | Infrastructure first, plug in LLM later |
| Damped confidence propagation | Phase 7 | Credibility is foundation, propagation layers on top |
| Semantic conflict detection | Research backlog | Requires embedding similarity + LLM verification |
| Configurable tier weights per silo | Phase 7+ | Start with semantic anchors, tune later |
| Calibration based on observed accuracy | Phase 7+ | Need usage data first |
| Primitives package update | After Phase 2 validation | Stabilize types before publishing |

## Directory Structure

Rename `brain/` to `sage/` - keep SAGE name, reactive implementation.

| File | Purpose |
|------|---------|
| `sage/transactions.py` | Core transactions (renamed from brain/), add FLAG_CONTRADICTION |
| `sage/consolidation.py` | ConflictQueue, ConsolidationWorker, DeterministicResolver |
| `sage/confidence.py` | Credibility formula, tier weights, breakdown helper |

Old SAGE Dagster jobs (`pipelines/jobs/`) removed in Phase 9.

## Data Model

### New Node Properties

```python
conflict_status: str   # 'none' | 'unresolved' | 'resolved_supersede' | 'resolved_merge' | 'resolved_coexist'
credibility: float     # static score computed at write time
```

Implicit defaults (no migration needed):
- Missing `conflict_status` = `'none'`
- Missing `credibility` = compute on read from existing fields

### CONTRADICTS Edge

- **Bidirectional:** A contradicts B creates A->B AND B->A (INV8)
- **Properties:**
  - `weight: float` - default 1.0, reduced for partial contradictions
  - `detected_at: datetime` - when conflict was detected
  - `conflict_type: str` - 'structural' (semantic later)

### New Edge Type

```python
RESOLVES  # (:resolution)-[:RESOLVES]->(:conflict_node)
```

Tracks what consolidation did for audit/debugging.

## Credibility Formula

Static credibility computed at write time:

```python
credibility = source_tier_weight * method_weight * raw_confidence
```

### Source Tier Weights (Semantic Anchors)

| Tier | Weight | Meaning |
|------|--------|---------|
| `authoritative` | 1.0 | Primary source: official docs, verified API response, direct observation |
| `validated` | 0.85 | Cross-checked against independent source |
| `community` | 0.6 | Unverified but from known-good agent/source |
| `unknown` | 0.4 | No provenance info |

### Method Weights

| Method | Weight | Meaning |
|--------|--------|---------|
| `direct` | 1.0 | Agent directly observed/verified |
| `validated_extractor` | 0.85 | Extraction pipeline with validation step |
| `standard_extractor` | 0.75 | Standard extraction, no validation |
| `experimental` | 0.6 | New/untested extraction method |

Method is inferred from context:
- MCP tool calls (`remember`, `learn`) default to `direct`
- Extraction pipeline sets method based on pipeline config
- If not specified, defaults to `direct` (1.0)

### Transparency Breakdown

Recall returns full breakdown so agents understand why scores are what they are:

```python
credibility_factors: {
    source_tier: "validated",
    source_tier_weight: 0.85,
    method: "direct",
    method_weight: 1.0,
    raw_confidence: 0.9,
    credibility: 0.765  # 0.85 * 1.0 * 0.9
}
```

## Conflict Detection (FLAG_CONTRADICTION)

### When

During TX2 STORE_CLAIM, after node creation succeeds.

### Detection Logic

```python
# Structural conflict: same (subject, predicate), different object
conflicts = query(
    silo_id=silo_id,
    subject=new_claim.subject,
    predicate=new_claim.predicate,
    object != new_claim.object,
    state=ACTIVE
)
```

### For Each Conflict

1. Create bidirectional CONTRADICTS edges (A->B and B->A)
2. Set `conflict_status='unresolved'` on both nodes
3. Emit `ConflictDetected` event

### No Blocking

TX2 still returns success. Conflict is flagged, not rejected. "Value is in retrieval with epistemic awareness, not autonomous belief formation."

### Event Payload

```python
ConflictDetected {
    node_a: str,
    node_b: str,
    silo_id: str,
    conflict_type: "structural",
    detected_at: datetime
}
```

## Consolidation Infrastructure

### Components

1. **Conflict Queue** - Silo-partitioned event queue using existing `ReactionEvent` pattern

2. **Consolidation Worker** - Async handler:
   - Claims conflict from queue
   - Gathers signals (credibility, recency, corroboration)
   - Calls resolver
   - Applies result

3. **Deterministic Resolver** (RESOLVE_CONFLICT):

```python
def score(claim):
    tier_weight = SOURCE_TIER_WEIGHTS[claim.source_tier]
    corroboration = claim.corroboration_count or 1
    freshness = 1.0 / (1 + days_since(claim.created_at))
    return tier_weight * log(1 + corroboration) * freshness

# Higher score wins
# Tie: same agent = newer wins, else older wins for stability
```

4. **LLM Resolver Stub** - Returns `'defer'` always. Ready for Phase 7 integration.

### Resolution Actions

| Action | Effect |
|--------|--------|
| `supersede` | Winner supersedes loser via TX3. Both get `conflict_status='resolved_supersede'` |
| `defer` | Stays `unresolved`. Re-queue when new evidence arrives |

Deferred actions (Phase 7+): `merge`, `coexist`

## CHECK_CORROBORATION (Atomic)

Single atomic query replacing Phase 1 placeholder.

### Cypher Query

```cypher
MATCH (new:Claim {id: $node_id, silo_id: $silo_id})
MATCH (c:Claim {silo_id: $silo_id})
WHERE c.properties.subject = new.properties.subject
  AND c.properties.predicate = new.properties.predicate
  AND c.properties.object = new.properties.object
  AND c.properties.state = 'ACTIVE'
WITH collect(c) AS claims
UNWIND claims AS claim
OPTIONAL MATCH (claim)-[:DERIVED_FROM]->(evidence)
WITH claims, collect(DISTINCT evidence.id) AS distinct_sources
UNWIND claims AS claim
SET claim.properties.corroboration_count = size(distinct_sources)
RETURN size(distinct_sources) AS count, size(distinct_sources) >= $threshold AS should_promote
```

### Implementation Notes

- Use `OPTIONAL MATCH` to handle claims without DERIVED_FROM edges
- Wrap in explicit serializable transaction at driver level (Memgraph driver)
- Default promotion threshold: 3 distinct sources
- If `should_promote`: emit `PromoteRequested` event (TX18 is Phase 3)

## Recall Changes

### RecallItem Additions

```python
RecallItem {
    # existing fields...
    
    # Conflict fields
    conflict_status: str,
    has_active_conflicts: bool,
    conflicting_nodes: list[str] | None,
    
    # Credibility breakdown
    credibility: float,
    credibility_factors: dict
}
```

### RecallResult Additions

```python
RecallResult {
    items: list[RecallItem],
    has_unresolved_conflicts: bool,  # any item with conflict_status='unresolved'
}
```

Agent sees `has_unresolved_conflicts=True` and knows retrieved knowledge has contested claims.

## Reaction Flow

```
TX2 STORE_CLAIM
    |
    +-> Create claim node (with credibility computed)
    |
    +-> Create DERIVED_FROM edges
    |
    +-> CHECK_CORROBORATION (atomic)
    |   +-> If threshold met: emit PromoteRequested event
    |
    +-> FLAG_CONTRADICTION (detect conflicts)
    |   +-> Create bidirectional CONTRADICTS edges
    |   +-> Set conflict_status='unresolved' on both
    |   +-> Emit ConflictDetected event
    |
    +-> Return success + existing async events


ConflictDetected event
    |
    +-> Consolidation Worker (async)
        +-> Gather signals
        +-> Call resolver (deterministic now, LLM stub returns 'defer')
        +-> Apply result
            +-> supersede: TX3_SUPERSEDE, update conflict_status
            +-> defer: leave unresolved
```

## Tasks

1. Rename `brain/` to `sage/`
2. Add credibility formula to `sage/confidence.py`
3. Fix CHECK_CORROBORATION in `sage/transactions.py`
4. Add FLAG_CONTRADICTION to TX2 flow
5. Create `sage/consolidation.py` with queue + worker + resolver
6. Update recall to surface conflict status and credibility breakdown
7. Add tests for conflict detection and consolidation
8. Update imports across codebase

## Success Criteria

- [ ] TX2 detects structural conflicts and creates bidirectional CONTRADICTS edges
- [ ] `conflict_status` set correctly on conflicting nodes
- [ ] CHECK_CORROBORATION is atomic (single query, driver-level transaction)
- [ ] Credibility computed at write with full breakdown available
- [ ] Consolidation worker processes ConflictDetected events
- [ ] Deterministic resolver picks winner based on score formula
- [ ] Recall surfaces conflict status and credibility factors
- [ ] All Phase 1 tests still pass after rename
