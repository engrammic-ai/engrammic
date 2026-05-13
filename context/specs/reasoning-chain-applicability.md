# Reasoning Chain Applicability Matching

**Status:** Shipped (v2.2)  
**Created:** 2026-05-11  
**Shipped:** 2026-05-12  
**Context:** [Discussion log](/home/novusedge/claude-bits/engrammic/2026-05-11-reasoning-chain-equivalence.md)

## Problem

Reasoning chain reuse requires determining when a cached chain can answer a new query. Naive structural hashing (steps + evidence) produces false positives: chains can share intermediate steps without being semantically substitutable.

Example: Two proofs of "sqrt(2) is irrational" via contradiction vs fundamental theorem of arithmetic have the same intent and conclusion but produce different understanding. They are not interchangeable.

## Key Insight

The question is not "are these chains identical?" but "can this chain answer the new query?" This is **applicability**, not identity.

Applicability depends on:
1. Query intent similarity
2. Reasoning path compatibility  
3. Evidence accessibility (can requesting context access the evidence this chain relied on?)

## Design

### Three-layer matching

**Layer 1: Query intent (fast filter)**
- Embed incoming query
- ANN search against cached query embeddings with silo_id filter
- Retrieve top-k candidates above threshold
- Latency: ~70ms (50ms embed + 20ms ANN)

**Layer 2: Step-level similarity (precision filter)**
- For each candidate chain, compare step embeddings via DTW
- Auto-extract step hints from session's in-progress reasoning (pre-computed)
- Require minimum similarity score
- Handles "same question, different reasoning path" case

**Layer 3: Evidence accessibility check**
- Verify all `evidence_used` nodes exist AND are accessible to requesting context
- Check via session/silo scoping
- Latency: ~20ms (batch node check)

### Write-time changes

**Current:**
```python
class ReasoningStep(BaseModel):
    step: int
    reasoning: str
    confidence: float | None = None
```

**New fields on ReasoningChain node:**
```python
query_embedding: list[float]       # embedding of the originating query
step_embeddings: list[list[float]] # embedding per step (pre-computed async)
```

**Write path (in `_context_reason`):**
```python
async def _context_reason(...):
    # ... existing chain creation logic ...
    
    chain_node = await create_chain_node(...)
    
    # Query embedding: sync (one call, ~50ms, acceptable)
    query_embedding = await embed(query)
    await attach_embedding(chain_node.id, "query", query_embedding)
    
    # Step embeddings: async (background task, no blocking)
    for step in steps:
        schedule_background_embed(chain_node.id, step.step, step.reasoning)
```

**Step embedding flow:**
- Agent stores reasoning step via `context_store`
- Background task embeds step, caches on session/WorkingHypothesis
- At lookup time, step embeddings already available (no inline embedding cost)

### Read-time flow

```python
async def find_applicable_chain(
    query: str,
    silo_id: str,
    session_id: str,
) -> Chain | None:
    
    config = get_config().reasoning_chain_matching
    
    # Auto-extract step hints from session
    step_hints = await get_session_step_embeddings(session_id)
    is_cold_start = len(step_hints) == 0
    
    # Layer 1: Query intent (with silo isolation)
    query_emb = embed(query)
    threshold = config.query_threshold_cold if is_cold_start else config.query_threshold_warm
    
    candidates = qdrant.search(
        query_emb,
        top_k=config.top_k_candidates,
        threshold=threshold,
        filter={"silo_id": silo_id}
    )
    
    if not candidates:
        return None
    
    # Layer 2: Step similarity (skip if cold-start)
    for chain in candidates:
        if is_cold_start:
            similarity_score = None  # explicitly null for cold-start
        else:
            similarity_score = dtw_similarity(chain.step_embeddings, step_hints)
            if similarity_score < config.step_threshold:
                continue
        
        # Layer 3: Evidence accessibility
        accessible = await get_accessible_nodes(silo_id, session_id)
        required = set(chain.evidence_used)
        
        if not required.issubset(accessible):
            continue
        
        # Log delivery for feedback tracking
        await log_chain_delivery(session_id, chain.id, query, similarity_score)
        
        return chain  # early exit on first match
    
    return None
```

### Cold-start behavior

When agent has no in-progress reasoning (step_hints empty):
- Layer 2 skipped
- Stricter query threshold (0.95 vs 0.88) compensates
- Any valid chain for the query intent is acceptable
- Agent profile matching deferred to future version

### Configuration

```yaml
reasoning_chain_matching:
  # Thresholds (defaults, will tune with data)
  query_threshold_cold: 0.95
  query_threshold_warm: 0.88
  step_threshold: 0.85
  
  # Candidates
  top_k_candidates: 5
  
  # Latency guards
  dtw_latency_warn_ms: 50
  dtw_latency_abort_ms: 100

chain_feedback:
  evaluation_delay_minutes: 5
  min_subsequent_steps: 3
  max_wait_minutes: 30
```

### Embedding model

**Decision:** Uniform with EAG, but configurable.

```yaml
reasoning_chain:
  model: ${EAG_EMBEDDING_MODEL}  # inherit by default
  # model: "custom/reasoning-tuned"  # override if needed
```

### Step alignment via DTW

**Decision:** Use `dtaidistance` library (hard dependency).

```toml
[project.dependencies]
dtaidistance = ">=2.3.0"
```

```python
from dtaidistance import dtw_ndim

def dtw_similarity(steps_a: list[list[float]], steps_b: list[list[float]]) -> float:
    distance = dtw_ndim.distance(steps_a, steps_b)
    return 1.0 / (1.0 + distance)
```

Complexity: O(n*m), ~10-20ms for typical chains. Early exit on first passing candidate.

### Evidence validity

**Decision:** Existence + accessibility only. No freshness check for v1.

Freshness check dropped because:
- Updated evidence might be better, not disqualifying
- Can't distinguish correction vs refinement without semantic diff
- Instrument for monitoring: track "chain returned where evidence modified post-creation"

Revisit freshness when we have change-type metadata or semantic diffing.

### Async embedding window

**Decision:** Graceful miss acceptable.

Chain written -> embeddings computed async -> brief window (~100-200ms) where chain exists but isn't findable. Acceptable tradeoff vs blocking writes.

## Metrics

**Retrieval metrics:**
- `reasoning.chain.lookup.latency_ms` - end-to-end lookup time
- `reasoning.chain.lookup.hit` - cache hit (bool)
- `reasoning.chain.lookup.layer_reached` - which layer rejected (1, 2, 3, or hit)
- `reasoning.chain.lookup.similarity_score` - query similarity of returned chain
- `reasoning.chain.lookup.cold_start` - was this a cold-start lookup (bool)

**Feedback metrics (from background job):**
- `reasoning.chain.feedback.useful` - agent followed the chain
- `reasoning.chain.feedback.not_useful` - agent ignored/re-derived
- `reasoning.chain.feedback.unclear` - insufficient signal

**Monitoring:**
- `reasoning.chain.evidence_modified_post_creation` - returned chain where evidence was updated after chain creation (for freshness decision revisit)

## Feedback system

### Implicit feedback via session correlation

No explicit agent action required. Background Dagster job analyzes session behavior.

**Chain delivery logging:**
```python
await log_chain_delivery(
    session_id=session_id,
    chain_id=chain.id,
    query=query,
    similarity_score=score,
    delivered_at=now()
)
```

**Background job (Dagster asset):**
```python
@asset
def chain_usefulness_signals():
    deliveries = get_chain_deliveries(last_hours=1)
    
    for d in deliveries:
        subsequent_steps = get_session_steps(
            session_id=d.session_id,
            after=d.delivered_at,
            limit=10
        )
        
        if not subsequent_steps:
            continue  # session idle
        
        overlap = step_similarity(d.chain.steps, subsequent_steps)
        new_chain = get_new_chains_in_session(
            session_id=d.session_id,
            after=d.delivered_at,
            query_similar_to=d.query
        )
        
        if overlap > 0.7:
            signal = "useful"
        elif new_chain:
            signal = "not_useful"
        else:
            signal = "unclear"
        
        store_feedback(d.chain_id, signal, timestamp=now())
```

**Storage (Postgres):**

```sql
CREATE TABLE chain_delivery (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    chain_id UUID NOT NULL,
    query TEXT NOT NULL,
    similarity_score FLOAT,  -- null for cold-start
    delivered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE chain_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chain_id UUID NOT NULL,
    signal TEXT NOT NULL,  -- 'useful', 'not_useful', 'unclear'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_delivery_session ON chain_delivery(session_id);
CREATE INDEX idx_delivery_time ON chain_delivery(delivered_at);
CREATE INDEX idx_feedback_chain ON chain_feedback(chain_id);
```

Postgres chosen for: ACID guarantees, aggregation queries for threshold tuning, existing infra.

**Weighting:** None for v1. Collect raw signals, analyze distribution, add decay if data shows it matters.

## Deferred

**LLM-generated step descriptors:** If step embeddings produce too many false positives (surface text similarity dominates), add LLM call at write time for canonical "logical role" descriptions. Requires prompting harness. Revisit after v1 data.

**Consumer preference / agent profile matching:** Allow agents to specify preferred reasoning style or match based on agent profile. Business logic decision, defer until cold-start precision becomes a problem.

**Partial chain reuse:** MemShare-style reuse of individual steps rather than full chains. Higher complexity, defer until full-chain reuse is validated.

**Feedback weighting:** Exponential decay or fixed window. Decide after analyzing signal distribution.

## Implementation phases

1. **Dependencies:** Add `dtaidistance>=2.3.0` to pyproject.toml
2. **Schema:** Add `query_embedding`, `step_embeddings` to ReasoningChain
3. **Write path:** Embed steps async on creation, cache on session
4. **Read path:** Implement `find_applicable_chain` with three-layer matching
5. **Delivery logging:** Log chain returns for feedback tracking  
6. **Metrics:** Wire up retrieval metrics
7. **Feedback job:** Dagster asset for usefulness signals
8. **Config:** YAML config for all tunable parameters
