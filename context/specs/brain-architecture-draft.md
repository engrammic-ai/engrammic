# Brain Architecture: Reactive System with Invariants

> Draft spec for replacing SAGE with a brain-shaped architecture. Status: DRAFT, not approved.

## Vision

Each silo is a **centralized brain** for its agents. Multiple agents read/write to a shared knowledge substrate. The brain:
- Reacts to input (not scheduled batches)
- Maintains consistency as invariant (not detected later)
- Synthesizes during idle time or on demand (not precomputed everything)
- Scales across many silos without linear infrastructure cost

## Current State (SAGE)

```
Write -> Queue -> [10-30 min later] -> Dagster Job -> Validate -> Synthesize -> Store
```

Problems:
- Latency: 10-30 minutes before brain "knows" anything
- Shape: ETL jobs, not reactive system
- Consistency: contradictions detected in batch, not prevented
- Cost: jobs run whether or not there's work
- Scalability: partitioned by silo, but all silos treated equally

## Target State

```
Write -> Inline checks -> Store -> [if needed] Enqueue reaction
                                -> [if idle] Consolidation
                                -> [if queried] Lazy synthesis
```

## Architecture Layers

### Layer 1: Write-Time (Inline, Sync, < 50ms added latency)

What happens on every write:

| Check | Description | Action on failure |
|-------|-------------|-------------------|
| Provenance | Node has required DERIVED_FROM edges | Reject write |
| Silo membership | All referenced nodes in same silo | Reject write |
| Structural contradiction | Same (s, p, o) with different value exists | Trigger resolution |
| Corroboration update | Another claim says the same thing | Increment corroboration count |

These are **invariants**, not validations. The brain never stores inconsistent state.

**Structural contradiction resolution (inline):**
- New claim contradicts existing claim
- Compare: source_tier, corroboration_count, freshness
- Winner stays, loser gets SUPERSEDES edge
- No LLM needed - pure deterministic rules

### Layer 2: Reaction Queue (Async, Event-Driven)

What gets enqueued after write:

| Trigger | Reaction | Priority |
|---------|----------|----------|
| New claim in hot cluster | Check synthesis threshold | heat x cluster_density |
| Corroboration count crossed threshold | Promote claim to fact | immediate |
| Potential semantic contradiction | LLM verification | medium |
| Evidence shift detected | Check belief revision | heat x shift_magnitude |

**Queue design:**
- Partitioned by silo_id (isolation)
- Priority queue within partition (heat-ranked)
- Workers claim partitions dynamically (scale horizontally)
- Dead letter queue for persistent failures

**Not scheduled**: Workers pull when work exists, not on cadence.

### Layer 3: Idle-Time Consolidation (Background, Low Priority)

Triggered when: no writes to silo for N seconds (configurable, default 60s)

What happens:
- Broader synthesis pass (clusters not yet synthesized)
- Pattern detection across facts
- Heat diffusion (update scores)
- Cleanup (tombstone GC, stale marker expiry)

**This is the "dreaming" phase.** Only runs when the brain is quiet.

**Scalability:**
- Idle detection per silo (not global)
- Low-priority workers handle consolidation
- Can be preempted if silo becomes active

### Layer 4: Query-Time Completion (On Demand)

When an agent queries an area without existing synthesis:

```
Agent: recall("OAuth token expiry patterns")
Brain: 
  1. Retrieve relevant facts
  2. Check: synthesis exists for this cluster?
  3. If no: synthesize now, cache as Belief
  4. Return facts + synthesis
```

**Lazy synthesis**: Don't precompute everything. Synthesize what's asked for.

**Cache policy:**
- Belief cached until underlying facts change
- Invalidation: any fact in SYNTHESIZED_FROM edges changes -> mark stale
- Stale belief: re-synthesize on next query

## Data Model Changes

### Beliefs

Current: Precomputed by sage.synthesizer, stored as nodes

New: Two types:
1. **Agent-authored Commitments** (via commit/crystallize) - stored, explicit
2. **System-synthesized Beliefs** - lazy, cached, invalidated on evidence change

Beliefs become more like **materialized views** than **ETL output**.

### ProposedBelief

Current: Intermediate state, requires accept/reject ceremony

New: **Delete entirely.** 
- High-confidence synthesis -> store directly
- Low-confidence -> don't synthesize, return facts only
- No ceremony, no validator approval

### Contradiction State

Current: Detected by sage.validator, writes Contradiction markers

New: **Contradictions cannot persist.**
- Structural: resolved inline at write time
- Semantic: resolved via reaction queue (LLM verification)
- If unresolved: block write or flag for human review (product decision)

## Scalability Model

### Per-Silo Isolation

Each silo is independent:
- Own event stream/queue partition
- Own idle detection
- Own synthesis cache
- No cross-silo reads or writes

### Horizontal Scaling

```
                    ┌─────────────────────┐
                    │   Event Stream      │
                    │ (partitioned by     │
                    │     silo_id)        │
                    └─────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼────┐          ┌────▼────┐          ┌────▼────┐
   │ Worker 1│          │ Worker 2│          │ Worker N│
   │ silos   │          │ silos   │          │ silos   │
   │ A, B, C │          │ D, E, F │          │ X, Y, Z │
   └─────────┘          └─────────┘          └─────────┘
```

Workers claim silo partitions. Hot silos can be rebalanced.

### Cost Model

| Activity | Current (SAGE) | New (Brain) |
|----------|----------------|-------------|
| Quiet silo | Jobs run anyway | No work, no cost |
| Active silo | Waits for next batch | Immediate reaction |
| LLM calls | Scheduled, all clusters | On-demand, requested clusters only |
| Infra | Dagster + workers always running | Workers scale to zero when idle |

## Migration Path

### Phase 1: Write-Time Invariants
- Move structural contradiction check to write time
- Move provenance check to write time
- Keep SAGE for everything else (parallel operation)

### Phase 2: Reaction Queue
- Replace Dagster sensors with event stream
- Workers pull from queue instead of scheduled runs
- SAGE jobs become fallback/backfill only

### Phase 3: Lazy Synthesis
- Query-time synthesis for uncached areas
- Belief invalidation on evidence change
- Remove precomputation from SAGE

### Phase 4: Deprecate SAGE
- Consolidation moves to idle-time workers
- Remove Dagster jobs (keep groundskeeper for GC)
- Remove ProposedBelief flow

## Open Questions

1. **Idle threshold**: How long without writes = "idle"? Per-silo configurable?

2. **Contradiction resolution policy**: What if structural rules can't decide winner? Block write? Flag for review? Store both with conflict marker?

3. **Synthesis confidence threshold**: Below what confidence do we not synthesize at all?

4. **Query-time latency budget**: If synthesis takes 2s, is that acceptable on first query?

5. **Cache invalidation granularity**: Invalidate whole belief on any fact change? Or smarter diffing?

6. **Hot silo thundering herd**: Many agents writing to same silo simultaneously - how to handle reaction queue backup?

7. **Cross-silo patterns**: Future feature? Or always silo-isolated?

## What Dies

- `sage.synthesizer` as scheduled job (becomes on-demand)
- `sage.validator` as batch checker (becomes write-time invariant)
- `sage.custodian` multi-phase visits (becomes simpler reaction handlers)
- `ProposedBelief` and accept/reject flow
- Dagster as primary execution substrate (keep for GC/backfill only)

## What Lives

- `sage.groundskeeper` for GC, decay, cleanup (still needed)
- Epistemology primitives (confidence, corroboration, contradiction detection)
- Layer semantics (Memory/Knowledge/Wisdom scoring differences)
- Provenance tracking (DERIVED_FROM, SYNTHESIZED_FROM edges)
- Heat/freshness signals (but computed differently)

## What's New

- Event stream / reaction queue infrastructure
- Write-time invariant checks
- Idle detection per silo
- Query-time synthesis with caching
- Belief invalidation on evidence change

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Time from write to "brain knows" | 10-30 min | < 5s (reactions), < 60s (synthesis) |
| Consistency violations | Detected later | Prevented at write |
| Cost for quiet silo | Same as active | Near zero |
| Synthesis relevance | Context-free | Query-context-aware (lazy) |

## Non-Goals (for now)

- Cross-silo knowledge sharing
- Multi-brain federation
- Real-time streaming to agents (push model)
- Belief confidence calibration

---

## Appendix: Comparison to Prior Art

### vs. Traditional KG + Reasoning Engine
Similar: reactive rules, consistency invariants
Different: LLM-based synthesis, not just logical inference

### vs. RAG
Similar: retrieval-augmented
Different: epistemic awareness, not just similarity search

### vs. Agent Memory (Letta, MemGPT)
Similar: persistent memory for agents
Different: multi-agent shared brain, not per-agent memory

### vs. SAGE
Same goals, different shape. SAGE is ETL; this is reactive system.
