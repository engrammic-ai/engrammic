# v2 Architecture Fixes Spec

Addresses P0-P3 issues identified in the 2026-05-07 architecture review.

## Goals

1. Align implementation with EAG spec (P0 philosophy gaps)
2. Eliminate dual-write divergence risk (P1 reliability)
3. Reduce protocol abstraction leakage (P1 debt)
4. Improve MCP tool ergonomics (P2 agent UX)
5. Fix minor correctness issues (P3)
6. Enable system-initiated belief synthesis (strategic differentiator)

## Non-Goals

- Event sourcing (no event log exists)
- LLM-based conflict detection (keeps 30ms budget)
- Backward compatibility (not public yet — just ship)

---

## P0-1: Async R1 Promotion

### Problem

`_context_assert` auto-promotes claims at write time, bypassing Custodian consensus path. Violates spec: T1 (Memory->Knowledge) should be signal-driven, Custodian-driven.

### Solution

Remove auto-promote from MCP write path. Return `pending_promotion` status.

### Changes

**Delete** in `mcp/tools/context_store.py` (lines 188-203):
```python
# REMOVE THIS BLOCK
if evidence_count >= 1:
    await ctx_svc.promote_claim_to_fact(...)
```

**Add** response shape change:
```python
return {
    "node_id": claim_id,
    "layer": "knowledge",
    "status": "pending_promotion",  # NEW
    "created_at": created_at,
}
```

### Verification

Confirmed: `pipelines/assets/fact_promotion.py` already handles async promotion:
- Scans `WHERE NOT c:Fact`
- Counts evidence via `REFERENCES|DERIVED_FROM` edges
- Calls `evaluate_claim_for_fact` with R1/R2 rules
- Scheduled via `fact_promotion_schedule`

No new Custodian work needed.

### Migration

None. Status field is additive.

---

## P0-2: Two-Phase Confidence Calibration

### Problem

Stores raw confidence floats, not calibrated values. Full formula requires corroboration which isn't known at write time.

### Solution

Two-phase calibration:
1. Write time: `partial_confidence = source_tier * method_weight * raw_confidence`
2. Promotion time: `final_confidence = partial_confidence * corroboration_factor`

### Changes

**In** `services/context.py::assert_claim`:

```python
from primitives.eag.epistemology.confidence import (
    partial_confidence, 
    SourceTier,
    MethodWeight,
)

# At write time (no corroboration yet):
calibrated = partial_confidence(
    raw_confidence=confidence,
    source_tier=SourceTier(source_tier or "unknown"),
    method_weight=MethodWeight.from_source_type(source_type),
)
# Store both:
# - raw_confidence (original input)
# - partial_confidence (calibrated without corroboration)
```

**In** `custodian/fact_promotion.py`:

```python
# At promotion time (corroboration known):
final = calibrated * corroboration_factor(corroborations)
# Store final_confidence on :Fact node
```

**Schema** — add fields to Claim/Fact:
```cypher
(:Claim {
  ...,
  raw_confidence: float,
  partial_confidence: float,  # NEW
})

(:Fact {
  ...,
  final_confidence: float,  # NEW (computed at promotion)
})
```

### Migration

Backfill `partial_confidence = raw_confidence * 0.7` (default source_tier weight) for existing Claims.

---

## P0-3: T3/T7 Commitment Distinction

### Problem

Synthesized beliefs (T3) and agent-authored commitments (T7) both write as `:Commitment` with no distinction.

### Solution

Add `kind` field, infer from provenance edges for backfill.

### Changes

**Schema**:
```cypher
(:Commitment {
  ...,
  kind: "rule" | "pattern" | "unknown"
})
```

**In** `mcp/tools/context_store.py` — wisdom branch:
```python
kind: Literal["rule", "pattern"] = "rule"
```

**In** `custodian/consensus_promotion.py` — T3 path:
```python
kind = "pattern"
```

**Backfill** `pipelines/assets/migrate_commitment_kind.py`:
```cypher
// Infer from provenance edges
MATCH (c:Commitment)
WHERE c.kind IS NULL
WITH c,
  EXISTS { (c)-[:SYNTHESIZED_FROM]->() } AS is_pattern,
  EXISTS { (c)-[:DECLARED_BY]->(:Agent) } AS is_rule
SET c.kind = CASE 
  WHEN is_pattern THEN "pattern"
  WHEN is_rule THEN "rule"
  ELSE "unknown"
END
```

### Migration

Run backfill asset once. Expected: ~70% rule, ~20% pattern, ~10% unknown.

---

## P1-1: Dual-Write Outbox

### Problem

Memgraph and Qdrant writes have no coordination. Crash between writes = inconsistent state.

### Solution

Outbox pattern with retry-before-return for Redis atomicity.

### Architecture

```
MCP write
    |
    v
services/context.py::store()
    |
    +-- 1. Write Memgraph node
    +-- 2. Write Redis outbox (3x retry on failure)
    |       { node_id, silo_id, content, status: "pending" }
    |
    +-- If Redis fails after 3 retries: fail entire request
    |
    return node_id
    .
    . (async, Dagster sensor)
    .
OutboxEmbedSensor (5s poll interval)
    |
    +-- 3. Read pending from outbox
    +-- 4. Embed content
    +-- 5. Qdrant upsert
    +-- 6. Mark outbox record done
    |
    On failure: retry 3x, then dead-letter
```

### Changes

**Remove** inline rollback in `services/context.py` (lines 315-336).

**New** `engine/outbox.py`:
```python
class OutboxWriter:
    async def enqueue(
        self, 
        node_id: str, 
        silo_id: str, 
        content: str,
        retries: int = 3,
    ) -> None:
        """LPUSH with retry. Raises if all retries fail."""
        for attempt in range(retries):
            try:
                await self.redis.lpush(f"outbox:{silo_id}", record.json())
                return
            except RedisError:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(0.1 * (attempt + 1))

class OutboxPoller:
    async def poll(self, batch_size: int = 10) -> list[OutboxRecord]: ...
    async def mark_done(self, record_id: str) -> None: ...
    async def dead_letter(self, record: OutboxRecord) -> None: ...
```

**New** `pipelines/sensors/outbox_embed_sensor.py`

**Update** `services/context.py::store()`:
```python
# After Memgraph write succeeds:
await outbox.enqueue(node_id, silo_id, content)  # Fails request if Redis down
# Remove try/except Qdrant block entirely
```

### Monitoring

- **Metric**: `outbox_queue_depth` per silo
- **Metric**: `outbox_processing_latency_p95`
- **Alert**: DLQ depth > 0 for > 5 minutes
- **Alert**: Queue depth > 1000

### Rollback Plan

If outbox causes regressions:
1. Revert to inline Qdrant writes (restore lines 315-336)
2. Keep outbox sensor running to drain existing queue
3. Investigate, fix, redeploy

---

## P1-2: Raw Cypher Escape Hatches

### Problem

`execute_query`, `execute_write`, `session()`, `transaction()` on `HyperGraphStore` protocol leak abstraction and make backend-swapping hard.

### Solution

Move to `RawCypherMixin`, deprecate from public protocol.

### Changes

**New** `engine/raw_cypher.py`:
```python
class RawCypherMixin:
    """Escape hatch for callers that need raw Cypher access.
    
    Intentionally separate from HyperGraphStore protocol.
    Callers must explicitly opt-in.
    """
    async def execute_query(self, query: str, params: dict) -> list[dict]: ...
    async def execute_write(self, query: str, params: dict) -> None: ...
    def session(self) -> AsyncSession: ...
    def transaction(self) -> AsyncTransaction: ...
```

**Update** `engine/memgraph_store.py`:
```python
class MemgraphStore(HyperGraphStore, RawCypherMixin):
    ...
```

**Update** `engine/protocols.py`:
- Remove `execute_query`, `execute_write`, `session`, `transaction` from `HyperGraphStore`
- Add deprecation note pointing to `RawCypherMixin`

**Migration**: Callers using raw Cypher must import `RawCypherMixin` explicitly. Grep and update.

---

## P1-3: Node Hydration Registry

### Problem

`_node_from_record` has 3 branches (document, passage, legacy). Will grow with new node types.

### Solution

Registry-dispatch pattern keyed on label.

### Changes

**New** `engine/hydration.py`:
```python
from typing import Callable, Any

_HYDRATORS: dict[str, Callable[[dict], Any]] = {}

def register_hydrator(label: str):
    def decorator(fn: Callable[[dict], Any]):
        _HYDRATORS[label] = fn
        return fn
    return decorator

def hydrate_node(record: dict) -> Any:
    labels = record.get("labels", [])
    for label in labels:
        if label in _HYDRATORS:
            return _HYDRATORS[label](record)
    return _default_hydrator(record)

@register_hydrator("Document")
def _hydrate_document(record: dict) -> Document: ...

@register_hydrator("Passage")
def _hydrate_passage(record: dict) -> Passage: ...

@register_hydrator("Claim")
def _hydrate_claim(record: dict) -> Claim: ...
```

**Update** `engine/memgraph_store.py`:
- Replace `_node_from_record` with `hydrate_node` call
- Remove branching logic

---

## P2: Tool Surface Refactor

### Problem

`context_admin` has ref/name collision. Need tools for ProposedBelief flow.

### Solution

Keep `context_store` unified (research shows <10 tools optimal for selection quality). Add 2 belief tools. Restructure `context_admin`.

### New Tools (2)

```python
context_accept_belief(belief_id, session_id?, silo_id?)
    -> {belief_id, status: "accepted", working_belief_id}

context_reject_belief(belief_id, reason?, silo_id?)
    -> {belief_id, status: "rejected"}
```

### Keep As-Is

- `context_store` — unified writes (improve error messages + docstring)
- `context_recall` — add `proposed_beliefs` to response
- `context_link`
- `context_belief_state`
- `context_update_belief`
- `context_crystallize`

### Restructure

`context_admin` — replace `ref`/`name` with explicit params:
```python
context_admin(
    action: Literal["provenance", "history", "create_silo", ...],
    node_id: str | None = None,
    chain_id: str | None = None,
    session_id: str | None = None,
    silo_id: str | None = None,
)
```

### Rationale

Research shows tool selection quality degrades >30 tools, optimal <10. Keeping unified approach: 7 + 2 = 9 tools.

Final tool count: 9 (was 7)

---

## P3-1: Timestamp Parameterization

### Problem

`PROMOTE_CLAIM_TO_FACT` uses `datetime()` directly instead of `$valid_from` parameter.

### Solution

Parameterize for reproducibility.

### Changes

**In** `db/queries.py`:
```cypher
// Before
SET f.created_at = datetime()

// After  
SET f.created_at = $promoted_at,
    f.valid_from = $valid_from
```

**In** `custodian/fact_promotion.py`:
```python
await client.execute_write(
    PROMOTE_CLAIM_TO_FACT,
    {
        ...,
        "promoted_at": datetime.now(UTC),
        "valid_from": datetime.now(UTC),
    },
)
```

---

## P3-2: Commitment valid_to on Finding Promotion

### Problem

Commitment stays open-ended when promoted to Finding, appears in active-node reads.

### Solution

Stamp `valid_to` on source Commitment.

### Changes

**In** `db/queries.py` — `CREATE_FINDING_FROM_COMMITMENT`:
```cypher
// Add after Finding creation:
SET cm.valid_to = $promoted_at
```

---

## NEW: System-Initiated Belief Synthesis

### Problem

Agents don't naturally formulate beliefs. Waiting for explicit calls limits adoption.

### Solution

System proposes beliefs from memory patterns. Agents accept/reject.

### New Node Type

```cypher
(:ProposedBelief {
  id: uuid,
  silo_id: string,
  content: string,
  confidence: float,
  status: "proposed" | "accepted" | "rejected",
  created_at: datetime,
  evidence_count: int
})

// Edges
(pb:ProposedBelief)-[:INFERRED_FROM]->(m:Memory)
(pb:ProposedBelief)-[:ACCEPTED_AS]->(wb:WorkingBelief)
```

### New Dagster Sensor

`pipelines/sensors/belief_synthesis_sensor.py`:
- Polls for silos with recent memory activity
- Clusters memories by entity/topic
- Proposes belief if cluster size >= 5 and confidence >= 0.7
- Rate limit: max 3 proposals per silo per hour

### Changes to context_recall

Surface proposals in response:
```python
return {
    "nodes": [...],
    "proposed_beliefs": [
        {
            "id": "...",
            "content": "User prefers concise responses",
            "confidence": 0.74,
            "evidence_count": 5,
            "evidence_ids": ["mem-1", "mem-2", ...]
        }
    ]
}
```

### Risk Mitigations

1. High threshold (>= 5 memories, >= 0.7 confidence)
2. Soft surfacing (proposals separate from confirmed)
3. Rejection learning (track rejections, reduce similar proposals)
4. Rate limiting (max 3 per session)
5. Opt-out (`silo_config.auto_synthesis = false`)

---

## Implementation Order

```
Batch 1 (one PR)
├── P0-1: pending_promotion status
├── P0-2: two-phase confidence
├── P0-3: kind field + edge-based backfill
├── P3-1: timestamp parameterization
└── P3-2: Commitment valid_to

Batch 2 (one PR, after Batch 1)
├── P1-1: outbox pattern
├── P1-2: raw Cypher mixin
└── P1-3: hydration registry

Batch 3 (one PR, after Batch 2 stable)
├── P2: tool surface refactor
└── ProposedBelief flow + new tools
```

---

## Success Criteria

- [ ] Knowledge writes return `status: "pending_promotion"`
- [ ] Claims store `raw_confidence` + `partial_confidence`
- [ ] Facts store `final_confidence` (with corroboration)
- [ ] Commitment nodes have `kind` field, backfill complete
- [ ] Zero inline Qdrant writes in `services/context.py`
- [ ] Outbox queue depth metric exposed
- [ ] DLQ alert configured
- [ ] `execute_query` removed from `HyperGraphStore` protocol
- [ ] `_node_from_record` replaced with registry dispatch
- [ ] New write tools registered, `context_store` deprecated
- [ ] `context_recall` returns `proposed_beliefs`
- [ ] `context_accept_belief` / `context_reject_belief` implemented
- [ ] All tools return `ignored_flags` when applicable

---

## Resolved Questions

1. **Confidence wiring**: Two-phase (partial at write, final at promotion)
2. **Backfill default**: Infer from edges, fallback to "unknown"
3. **Outbox atomicity**: 3x retry on Redis LPUSH, fail request if down
4. **Dead-letter threshold**: 3 attempts
5. **Deprecation period**: 2 sprints

## Open Questions

1. Should rejected beliefs inform future synthesis? (negative signal learning)
2. Proposal rate limit: 3 per hour or per session?

---

## References

- Architecture review: `context/intel/architecture-review-2026-05-07.md`
- Brainstorm: `context/brainstorm/architecture-fixes-2026-05-07.md`
- Belief formation strategy: `context/specs/belief-formation-strategy.md`
- Transitions spec: `context/specs/transitions.md`
- Competitive landscape: `context/intel/competitive-landscape-2026-05.md`
- EAG spec: `../primitives/context/specs/`
