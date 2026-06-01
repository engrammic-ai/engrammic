# Phase 3: Belief Flow Transactions Design

**Status:** Approved  
**Date:** 2026-06-01  
**Branch:** `feat/brain-architecture`

## Overview

Implement Phase 3 of the brain architecture: Belief Flow transactions (TX4, TX5, TX8, TX14). These transactions handle synthesis of beliefs from fact clusters and the agent hypothesis-to-commitment flow.

## Transactions

| TX | Name | Purpose | LLM Required |
|----|------|---------|--------------|
| TX4 | SYNTHESIZE | Create Belief from fact cluster | Yes |
| TX5 | REVISE_BELIEF | Re-synthesize stale belief | Yes |
| TX8 | COMMIT | Direct stance declaration | No |
| TX14 | CRYSTALLIZE | WorkingHypothesis to Commitment | No |

## Architecture Decision

**Option A selected:** Extend `sage/transactions.py` with all 4 transactions.

Rationale:
- Single source of truth for transaction logic
- Consistent patterns (typed results, ReactionEvents, invariant enforcement)
- LLM calls are implementation details, not domain boundaries
- 1400 lines is maintainable; can split later with better information

## Section 1: New Types and Result Dataclasses

```python
class SynthesisState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"

class ClusterState(StrEnum):
    SPARSE = "SPARSE"
    READY = "READY"
    SYNTHESIZED = "SYNTHESIZED"
    STALE = "STALE"

@dataclass
class SynthesizeResult:
    belief_id: uuid.UUID | None
    cluster_id: str
    cluster_state: ClusterState
    fact_count: int
    confidence: float | None
    timed_out: bool = False

@dataclass
class ReviseBeliefResult:
    new_belief_id: uuid.UUID | None
    old_belief_id: uuid.UUID
    content_changed: bool
    invalidated: bool = False

@dataclass
class CommitResult:
    commitment_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float

@dataclass
class CrystallizeResult:
    commitment_id: uuid.UUID
    hypothesis_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float
```

## Section 2: TX8 COMMIT and TX14 CRYSTALLIZE

### TX8 COMMIT

Agent declares a stance directly without prior hypothesis. Backs the `believe` MCP tool.

```python
async def tx8_commit(
    store: HyperGraphStore,
    content: str,
    about_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> tuple[CommitResult, list[ReactionEvent]]:
```

**Preconditions:**
- Agent has write access to silo (authz check)
- `about_refs` non-empty (commitment must be about something)
- All `about_refs` exist in same silo (INV5)
- All `about_refs` not tombstoned

**Creates:**
- Commitment node in Wisdom layer
- ABOUT edges to referenced nodes
- DECLARED_BY edge to agent (INV7)

### TX14 CRYSTALLIZE

Converts a session-scoped WorkingHypothesis to a permanent Commitment. Backs the `commit` MCP tool.

```python
async def tx14_crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
```

**Preconditions:**
- Hypothesis exists, not tombstoned, belongs to agent's session
- Hypothesis not already crystallized
- All ABOUT refs still valid (not tombstoned)

**Creates:**
- Commitment node copying content/confidence from hypothesis
- ABOUT edges (copied from hypothesis)
- DECLARED_BY edge to agent (INV7)
- CRYSTALLIZED_FROM edge for provenance

**Updates:**
- `hypothesis.crystallized = true`
- `hypothesis.crystallized_into = commitment_id`

## Section 3: TX4 SYNTHESIZE

Creates a Belief from a cluster of Facts. Most complex transaction with LLM integration.

```python
async def tx4_synthesize(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
) -> tuple[SynthesizeResult, list[ReactionEvent]]:
```

**Modes:**
- `ASYNC`: Background synthesis, 30s timeout, full retry logic
- `SYNC`: Query-time lazy synthesis, 2s timeout, return partial on timeout

**Preconditions:**
- Cluster exists with state READY or STALE
- No synthesis already in progress (deduplication)

**Flow:**
1. Acquire lock on cluster_id
2. Mark `synthesis_in_progress = true`
3. Fetch ACTIVE facts in cluster (up to MAX_CLUSTER_SIZE=1000)
4. If `fact_count < SYNTHESIS_THRESHOLD` (3): mark SPARSE, return null
5. Compute aggregate confidence via noisy-or
6. If `confidence < 0.6`: skip synthesis, return null
7. Call LLM with facts (uses existing `_SYNTHESIS_SYSTEM_PROMPT`)
8. On timeout (sync mode): return null with `timed_out=true`
9. Create Belief node with SYNTHESIZED_FROM edges to facts (INV3)
10. Update cluster: `state=SYNTHESIZED`, `current_belief_id=belief_id`

**Async reactions:**
- `compute_embedding(belief_id)`
- `update_heat(belief_id, SYNTHESIS)`

**Lock handling:** Use try/finally to ensure `synthesis_in_progress = false` on any exit (success, failure, timeout). On LLM failure, cluster state returns to READY (not stuck locked).

**Deduplication:** If synthesis already in progress, sync mode waits (up to timeout), async mode returns early.

**Confidence aggregation:** Noisy-or: `1 - product(1 - c_i)` gives higher aggregate when multiple facts agree.

## Section 4: TX5 REVISE_BELIEF

Re-synthesizes a stale Belief when underlying facts change. Creates a new Belief that supersedes the old one.

```python
async def tx5_revise_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
```

**Preconditions:**
- Belief exists with `state=ACTIVE`
- `belief.synthesis_state = STALE`
- No revision already in progress for this belief (`revision_in_progress = false`)

**Flow:**
1. Get `cluster_id` from `belief.source_cluster_id`
2. Mark `belief.revision_in_progress = true` (prevents duplicate SUPERSEDES chains)
3. Acquire lock on cluster_id
3. Fetch current ACTIVE facts in cluster
4. If `fact_count < threshold`: mark belief INVALIDATED, return
5. Recompute aggregate confidence
6. If `confidence < threshold`: mark belief INVALIDATED, return
7. Call LLM with facts + `previous_belief` context
8. If content unchanged: mark belief FRESH, return existing belief_id
9. Create new Belief node
10. Create SUPERSEDES edge (`reason=EVIDENCE_SHIFT`) from new to old
11. Mark old belief SUPERSEDED
12. Update `cluster.current_belief_id`

**Key differences from TX4:**
- LLM gets `previous_belief` content for continuity
- Content comparison to avoid unnecessary supersession
- Creates supersession chain rather than first belief

**Staleness trigger:** TX5 gets enqueued when CASCADE_STALENESS marks a belief as STALE.

**Retry logic:** On LLM failure, increment `cluster.synthesis_retry_count`, enqueue retry with exponential backoff (max 3 attempts).

## Section 5: Helper Functions and Integration

### New helpers

```python
def noisy_or_aggregate(confidences: list[float]) -> float:
    """Noisy-or: 1 - product(1 - c_i). Higher when multiple sources agree."""

async def llm_synthesize(
    llm: LLMProvider,
    facts: list[dict[str, Any]],
    timeout: float,
    previous_belief: str | None = None,
) -> SynthesisResult:
    """Call LLM to synthesize belief from facts."""

async def check_synthesis_trigger(store, cluster_id, silo_id) -> None:
    """Called when cluster membership changes. Enqueues TX4 if threshold met."""

async def wait_for_synthesis(store, cluster_id, timeout) -> uuid.UUID | None:
    """Sync mode deduplication - wait for in-progress synthesis."""
```

### Integration with existing code

1. **MCP tools unchanged** - `hypothesize` and `commit` tools keep their signatures
2. **Wire believe tool** - `believe.py` currently delegates to `_context_commit` (crystallize path). Add separate code path to TX8 for direct stance (no prior hypothesis)
3. **Deprecate engine/synthesis.py** - `synthesize_belief()` delegates to `tx4_synthesize()`
4. **Reuse queries** - `GET_FACTS_IN_CLUSTER`, `CREATE_BELIEF_FROM_FACTS` from `db/queries.py`

### New Cypher queries

```cypher
-- GET_CLUSTER_FOR_SYNTHESIS (with lock)
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
SET c.synthesis_in_progress = true
RETURN c.state, c.current_belief_id, c.synthesis_retry_count

-- CREATE_BELIEF_WITH_EDGES
CREATE (b:Node:Belief {
    id: $id, silo_id: $silo_id, content: $content,
    properties: $props, created_at: $created_at
})
WITH b
UNWIND $fact_ids AS fid
MATCH (f {id: fid, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN b.id

-- CREATE_COMMITMENT_WITH_DECLARED_BY (for TX8)
CREATE (c:Node:Commitment {
    id: $id, silo_id: $silo_id, content: $content,
    properties: $props, created_at: $created_at
})
WITH c
UNWIND $about_ids AS aid
MATCH (a {id: aid, silo_id: $silo_id})
CREATE (c)-[:ABOUT]->(a)
WITH c
CREATE (c)-[:DECLARED_BY {created_at: $created_at}]->(:Agent {id: $agent_id})
RETURN c.id

-- CREATE_CRYSTALLIZED_FROM_EDGE (for TX14 provenance)
MATCH (commitment {id: $commitment_id, silo_id: $silo_id})
MATCH (hypothesis {id: $hypothesis_id, silo_id: $silo_id})
CREATE (commitment)-[:CRYSTALLIZED_FROM {created_at: $created_at}]->(hypothesis)
```

**Note:** `CRYSTALLIZED_FROM` is an edge type (not a property) for provenance tracking.

## Section 6: Testing Strategy

### Test cases

**TX8 COMMIT:**
- `test_tx8_commit_creates_commitment_with_about_edges`
- `test_tx8_commit_creates_declared_by_edge` (INV7)
- `test_tx8_commit_rejects_empty_about_refs`
- `test_tx8_commit_rejects_cross_silo_refs` (INV5)
- `test_tx8_commit_rejects_tombstoned_refs`

**TX14 CRYSTALLIZE:**
- `test_tx14_crystallize_converts_hypothesis_to_commitment`
- `test_tx14_crystallize_copies_about_edges`
- `test_tx14_crystallize_creates_crystallized_from_edge`
- `test_tx14_crystallize_rejects_wrong_session`
- `test_tx14_crystallize_rejects_already_crystallized`
- `test_tx14_crystallize_rejects_invalid_about_refs`

**TX4 SYNTHESIZE:**
- `test_tx4_synthesize_creates_belief_from_cluster`
- `test_tx4_synthesize_skips_sparse_cluster`
- `test_tx4_synthesize_skips_low_confidence`
- `test_tx4_synthesize_deduplicates_concurrent_calls`
- `test_tx4_synthesize_sync_mode_timeout`
- `test_tx4_synthesize_creates_synthesized_from_edges` (INV3)

**TX5 REVISE_BELIEF:**
- `test_tx5_revise_belief_creates_new_belief`
- `test_tx5_revise_belief_supersedes_old`
- `test_tx5_revise_belief_skips_unchanged_content`
- `test_tx5_revise_belief_invalidates_unsupported`
- `test_tx5_revise_belief_retries_on_llm_failure`

### LLM mocking

Use `unittest.mock.AsyncMock` for `LLMProvider.complete()` - return canned synthesis results.

### Migration plan

1. Add transactions to `sage/transactions.py`
2. Add new queries to `db/queries.py`
3. Wire MCP tools to new transactions
4. Add `engine/synthesis.py` deprecation
5. Update existing tests

## Out of Scope

- Event queue infrastructure (Phase 8)
- Actual async worker processing (Phase 8)
- ReactionEvents are emitted but not consumed yet

## Related Documents

- `context/plans/2026-06-01-brain-architecture.md` - Phase plan
- `context/specs/brain-transactions-pseudocode.md` - Detailed pseudocode
- `context/specs/brain-transactions-overview.md` - Entity/state tables
