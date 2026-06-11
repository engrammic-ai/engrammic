# TX6 CONSENSUS + TX7 TRACE Spec

**Status:** Draft (reviewed)  
**Date:** 2026-06-11  
**Depends on:** Reasoning chain applicability (shipped), Phase 8 reactions

---

## Overview

Two related transactions for the Intelligence layer:

- **TX7 TRACE:** Persist WorkingHypothesis as ReasoningChain when session ends
- **TX6 CONSENSUS:** Promote to Fact when K chains from J agents agree

TX7 feeds TX6: persisted chains become candidates for consensus matching.

### Layer Transitions (corrected)

| TX | Spec says | Actually |
|----|-----------|----------|
| TX7 TRACE | Intelligence -> Memory | Intelligence -> Intelligence (WorkingHypothesis -> ReasoningChain) |
| TX6 CONSENSUS | Intelligence -> Knowledge | Correct (ReasoningChain -> Fact) |

Note: brain-transactions-overview says TX7 is "Intelligence -> Memory" but we're creating ReasoningChain nodes which are Intelligence layer. The overview should be updated.

---

## TX7 TRACE

### Trigger

Session end, detected by:
1. **Inactivity timeout** (default 30 min) - Primary mechanism
2. **Explicit session close** - If harness sends signal (not all do)
3. **Agent calls `commit` or `crystallize`** - Reasoning complete

Implementation: Redis key with TTL for session last-activity. When key expires, emit TRACE_REASONING event.

### Flow

```
WorkingHypothesis (session-scoped) -> ReasoningChain (permanent)
```

### Handler

```python
@broker.task(task_name=ReactionEventType.TRACE_REASONING, timeout=10_000)
async def trace_reasoning_task(session_id: str, silo_id: str, **_payload: Any) -> None:
    """Persist session's WorkingHypothesis as ReasoningChain."""
    
    # 1. Fetch session's hypotheses
    hypotheses = await get_session_hypotheses(session_id, silo_id)
    if not hypotheses:
        return
    
    # 2. For each hypothesis with steps, create ReasoningChain
    for hyp in hypotheses:
        if hyp.state == "committed":
            continue  # Already traced via commit flow
        
        chain_id = await postgres.insert(
            ReasoningChainSteps(
                chain_id=uuid4(),
                silo_id=silo_id,
                steps=hyp.steps,
                query_embedding=hyp.query_embedding,
                step_embeddings=hyp.step_embeddings,
                source_hypothesis_id=hyp.id,
                agent_id=hyp.agent_id,
                conclusion=hyp.content,
                conclusion_confidence=hyp.confidence,
            )
        )
        
        # 3. Create TRACED_FROM edge
        await graph_store.create_edge(
            from_id=chain_id,
            to_id=hyp.id,
            edge_type=CITEEdgeType.TRACED_FROM,
            silo_id=silo_id,
        )
        
        # 4. Trigger consensus check
        await emit_reaction(
            ReactionEventType.CHECK_CONSENSUS,
            chain_id=str(chain_id),
            silo_id=silo_id,
        )
    
    # 5. Mark session hypotheses as traced (prevents re-trace)
    await mark_hypotheses_traced(session_id, silo_id)
```

### Session State Model

Session tracking via Redis:

```python
# On any hypothesis activity
await redis.set(f"session:{session_id}:last_activity", now(), ex=SESSION_TIMEOUT_SECONDS)

# Session cleanup job (runs every 5 min)
async def cleanup_expired_sessions():
    # Find sessions where key expired (TTL passed)
    # For each, emit TRACE_REASONING
    expired = await find_expired_sessions()
    for session_id, silo_id in expired:
        await emit_reaction(ReactionEventType.TRACE_REASONING, session_id=session_id, silo_id=silo_id)
```

---

## TX6 CONSENSUS

### Trigger

ReasoningChain created (via TX7 TRACE or explicit commit).

### Flow

```
K ReasoningChains from J agents with similar conclusions -> Fact (Knowledge layer)
```

### Matching Strategy

Reuse existing reasoning chain applicability (3-layer):

1. **Conclusion similarity:** Embed chain conclusion, ANN search for similar conclusions
2. **Reasoning compatibility:** DTW on step embeddings (same conclusion via compatible paths)
3. **Agent diversity:** Require chains from >= J distinct agents

### Handler

```python
CONSENSUS_THRESHOLD_K = 3  # Minimum chains
CONSENSUS_THRESHOLD_J = 2  # Minimum distinct agents
CONCLUSION_SIMILARITY_THRESHOLD = 0.85

@broker.task(task_name=ReactionEventType.CHECK_CONSENSUS, timeout=15_000)
async def check_consensus_task(chain_id: str, silo_id: str, **_payload: Any) -> None:
    """Check if chain participates in consensus, promote to Fact if so."""
    
    # 1. Get the triggering chain
    chain = await get_reasoning_chain(chain_id, silo_id)
    if not chain or not chain.conclusion:
        return
    
    # 2. Find similar conclusions (Layer 1)
    similar_chains = await qdrant.search(
        collection="reasoning_chains",
        vector=chain.conclusion_embedding,
        filter={"silo_id": silo_id, "exclude_id": chain_id},
        threshold=CONCLUSION_SIMILARITY_THRESHOLD,
        limit=20,
    )
    
    # 3. Filter by reasoning compatibility (Layer 2)
    compatible = []
    for candidate in similar_chains:
        if await is_reasoning_compatible(chain, candidate):
            compatible.append(candidate)
    
    # 4. Check agent diversity
    all_chains = [chain] + compatible
    unique_agents = {c.agent_id for c in all_chains}
    
    if len(all_chains) < CONSENSUS_THRESHOLD_K:
        return  # Not enough chains yet - will re-check when more arrive
    if len(unique_agents) < CONSENSUS_THRESHOLD_J:
        return  # Not enough agent diversity
    
    # 5. Check if consensus already exists for this conclusion
    existing = await find_existing_consensus_fact(chain.conclusion_embedding, silo_id)
    if existing:
        # Add this chain to existing consensus
        await graph_store.create_edge(
            from_id=existing.id,
            to_id=chain_id,
            edge_type=CITEEdgeType.PROMOTED_FROM,  # INV2 compliance
            silo_id=silo_id,
        )
        await graph_store.create_edge(
            from_id=existing.id,
            to_id=chain_id,
            edge_type=CITEEdgeType.CONSENSUS_FROM,  # Additional provenance
            silo_id=silo_id,
        )
        await update_consensus_confidence(existing.id, len(all_chains))
        return
    
    # 6. Create new Fact from consensus
    fact_id = await store_fact_from_consensus(
        conclusion=chain.conclusion,
        supporting_chains=all_chains,
        silo_id=silo_id,
    )
    
    logger.info(
        "consensus_reached",
        fact_id=str(fact_id),
        chain_count=len(all_chains),
        agent_count=len(unique_agents),
        silo_id=silo_id,
    )


async def store_fact_from_consensus(
    conclusion: str,
    supporting_chains: list[ReasoningChain],
    silo_id: str,
) -> UUID:
    """Create Fact with PROMOTED_FROM + CONSENSUS_FROM edges to supporting chains."""
    
    # Confidence scales with chain count and agent diversity
    agent_count = len({c.agent_id for c in supporting_chains})
    base_confidence = min(0.95, 0.6 + (len(supporting_chains) * 0.05) + (agent_count * 0.1))
    
    fact_id = await graph_store.create_node(
        layer=PersistenceLayer.KNOWLEDGE,
        node_type=KnowledgeLabel.FACT,
        content=conclusion,
        confidence=base_confidence,
        silo_id=silo_id,
        metadata={
            "source": "consensus",
            "chain_count": len(supporting_chains),
            "agent_count": agent_count,
        },
    )
    
    # Link to all supporting chains with BOTH edge types
    for chain in supporting_chains:
        # PROMOTED_FROM satisfies INV2: "Every Fact has >= 1 DERIVED_FROM to Memory OR PROMOTED_FROM to ReasoningChain"
        await graph_store.create_edge(
            from_id=fact_id,
            to_id=chain.chain_id,
            edge_type=CITEEdgeType.PROMOTED_FROM,
            silo_id=silo_id,
        )
        # CONSENSUS_FROM provides additional provenance (which chains agreed)
        await graph_store.create_edge(
            from_id=fact_id,
            to_id=chain.chain_id,
            edge_type=CITEEdgeType.CONSENSUS_FROM,
            silo_id=silo_id,
        )
    
    # Trigger downstream reactions
    await emit_reaction(ReactionEventType.COMPUTE_EMBEDDING, node_id=str(fact_id), silo_id=silo_id)
    await emit_reaction(ReactionEventType.UPDATE_CLUSTER_MEMBERSHIP, node_id=str(fact_id), silo_id=silo_id)
    
    return fact_id
```

### Reasoning Compatibility Check

```python
from fastdtw import fastdtw
from scipy.spatial.distance import cosine

REASONING_COMPATIBILITY_THRESHOLD = 0.5

async def is_reasoning_compatible(chain_a: ReasoningChain, chain_b: ReasoningChain) -> bool:
    """Check if two chains have compatible reasoning paths via DTW."""
    
    if not chain_a.step_embeddings or not chain_b.step_embeddings:
        return True  # No step data, assume compatible
    
    # DTW on step embeddings
    distance, _ = fastdtw(
        chain_a.step_embeddings,
        chain_b.step_embeddings,
        dist=cosine
    )
    
    # Normalize by path length
    max_len = max(len(chain_a.step_embeddings), len(chain_b.step_embeddings))
    similarity = 1.0 - (distance / max_len)
    
    return similarity > REASONING_COMPATIBILITY_THRESHOLD
```

Dependency: `fastdtw` library (pip install fastdtw)

---

## Staleness Cascade

When a supporting ReasoningChain is tombstoned:

1. Mark consensus Fact as STALE
2. Trigger TX5 REVISE_BELIEF to re-evaluate
3. If remaining chains < K, tombstone the Fact

This uses existing staleness cascade, not direct confidence decay.

```python
# In tombstone handler for ReasoningChain
async def on_chain_tombstoned(chain_id: str, silo_id: str):
    # Find Facts with CONSENSUS_FROM edge to this chain
    facts = await graph_store.query(
        "MATCH (f:Fact)-[:CONSENSUS_FROM]->(c) WHERE c.id = $chain_id RETURN f",
        chain_id=chain_id
    )
    for fact in facts:
        await emit_reaction(ReactionEventType.CASCADE_STALENESS, node_id=str(fact.id), silo_id=silo_id)
```

---

## Schema Additions

### EdgeTypes (add to primitives)

```python
# In primitives/src/primitives/schema/edges.py CITEEdgeType
TRACED_FROM = "TRACED_FROM"      # ReasoningChain -> WorkingHypothesis
CONSENSUS_FROM = "CONSENSUS_FROM"  # Fact -> ReasoningChain (provenance)
# PROMOTED_FROM already exists and satisfies INV2
```

### ReactionEventTypes

```python
# In src/context_service/reactions/events.py
TRACE_REASONING = "trace_reasoning"  # Session ended, persist hypotheses
CHECK_CONSENSUS = "check_consensus"  # Chain created, check for agreement
```

### ReasoningChainSteps (extend existing)

```python
# Add to src/context_service/models/postgres/reasoning.py
conclusion: Mapped[str | None] = mapped_column(String, nullable=True)
conclusion_embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float), nullable=True)
agent_id: Mapped[str | None] = mapped_column(String, nullable=True)
source_hypothesis_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
traced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

### Qdrant Collection

```python
# Create reasoning_chains collection with conclusion embeddings
await qdrant.create_collection(
    collection_name="reasoning_chains",
    vectors_config=VectorParams(size=EMBEDDING_DIM, distance=Distance.COSINE),
)
```

---

## Configuration

```yaml
# Consensus thresholds
CONSENSUS_MIN_CHAINS: 3
CONSENSUS_MIN_AGENTS: 2
CONSENSUS_CONCLUSION_THRESHOLD: 0.85
CONSENSUS_REASONING_THRESHOLD: 0.5

# Trace settings
SESSION_TIMEOUT_MINUTES: 30
TRACE_ON_COMMIT: true  # Auto-trace when commit/crystallize called
```

---

## Observability

### Metrics

```python
consensus_checks_total              # CHECK_CONSENSUS events received
consensus_reached_total             # New consensus Facts created
consensus_extended_total            # Chains added to existing consensus
consensus_skipped_total{reason}     # Skipped (not enough chains/agents)
trace_reasoning_total               # Sessions traced
trace_chains_created_total          # Chains persisted
```

---

## Implementation Tasks

### Primitives

1. [ ] Add `TRACED_FROM` to `CITEEdgeType` in primitives
2. [ ] Add `CONSENSUS_FROM` to `CITEEdgeType` in primitives
3. [ ] Add `OBSERVATION` to `MemoryLabel` in primitives (cross-cutting)

### TX7 TRACE

4. [ ] Add `TRACE_REASONING` to ReactionEventType
5. [ ] Extend ReasoningChainSteps model (conclusion, agent_id, etc.)
6. [ ] Implement session state tracking (Redis TTL)
7. [ ] Implement `trace_reasoning_task` handler
8. [ ] Wire `emit_reaction` into commit/crystallize flow
9. [ ] Add session cleanup job or sensor

### TX6 CONSENSUS

10. [ ] Add `CHECK_CONSENSUS` to ReactionEventType
11. [ ] Create `reasoning_chains` Qdrant collection
12. [ ] Implement `check_consensus_task` handler
13. [ ] Implement `is_reasoning_compatible` with fastdtw
14. [ ] Implement `store_fact_from_consensus` with dual edges
15. [ ] Wire staleness cascade for chain tombstoning
16. [ ] Add config flags

### Testing

17. [ ] `test_trace_persists_hypothesis` - TX7 happy path
18. [ ] `test_trace_idempotent` - No duplicate chains
19. [ ] `test_consensus_requires_k_chains` - Threshold enforcement
20. [ ] `test_consensus_requires_j_agents` - Agent diversity
21. [ ] `test_consensus_creates_fact_with_both_edges` - PROMOTED_FROM + CONSENSUS_FROM
22. [ ] `test_consensus_extends_existing` - Add to existing fact
23. [ ] `test_chain_tombstone_cascades_to_fact` - Staleness propagation

---

## Resolved Questions

1. **Session detection:** Inactivity timeout (30 min default) via Redis TTL + explicit signal if harness sends it. Timeout is primary, explicit is bonus.

2. **Partial consensus:** No partial artifacts. If 2/3 required agents agree, just wait. The check re-runs when next chain arrives. No ProposedBelief (eliminated per brain-transactions Section 12).

3. **Confidence decay:** Via staleness cascade, not direct decay. When chain tombstoned, mark Fact STALE and trigger TX5 REVISE_BELIEF. This respects the epistemology model.

4. **Cross-silo consensus:** Never. INV5 prohibits cross-silo edges. If shared knowledge needed, explicitly replicate to both silos with own provenance chain.

---

## Related

- `context/specs/reasoning-chain-applicability.md` - Matching algorithm (shipped)
- `src/context_service/models/postgres/reasoning.py` - Existing storage
- `context/specs/brain-transactions-overview.md` - TX6/TX7 definitions (needs layer transition fix)
- `primitives/src/primitives/schema/edges.py` - CITEEdgeType
