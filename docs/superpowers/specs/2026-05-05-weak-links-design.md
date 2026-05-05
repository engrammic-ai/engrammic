# Weak Links with Signal Accumulation

**Date:** 2026-05-05  
**Status:** Draft  
**Approach:** B (Ingest + Signal Accumulation)

## Problem

Agents need to discover related context beyond explicit relationships. Current state:
- Embeddings go to Qdrant for search (no graph edges)
- Extraction creates explicit edges (DERIVES_FROM, typed triples)
- No auto-linking based on semantic similarity

**Goals:**
1. Pre-compute likely connections to avoid expensive similarity search at query time
2. Generate hypotheses for custodian/agent investigation
3. Enable discovery of related content through graph traversal

## Design Overview

Create speculative RELATED_TO edges during ingest based on embedding similarity. Track edge usage via access events. Custodian promotes high-signal edges and prunes unused ones.

```
[Ingest] --> [Embedding] --> [Weak Link Creation]
                                    |
                                    v
[Query] --> [Edge Traversal] --> [Edge Access Event]
                                    |
                                    v
[Hourly] --> [Edge Heat Asset] --> [weak_link_review Asset]
                                    |
                            +-------+-------+
                            |               |
                            v               v
                       [Promote]        [Prune]
```

## Section 1: Edge Creation (Ingest-time)

**When:** After embedding asset embeds a node  
**How:** Query Qdrant for top-K similar nodes  
**Creates:** RELATED_TO edge with speculative flag

### Edge Properties

```python
{
    "id": "<deterministic_uuid>",
    "weight": <cosine_score * initial_weight_multiplier>,
    "speculative": True,
    "created_at": "<timestamp>",
    "source": "embedding_similarity",
    "edge_heat": 0.0,
    "heat_updated_at": None
}
```

### Constraints

- Only between nodes in same silo
- Skip if explicit edge already exists between the pair
- Skip self-links
- Cap at max_links_per_node (default 5) to avoid fan-out explosion
- Minimum similarity threshold (default 0.75)

### Implementation

Extend embedding asset or create new `weak_link_creation` asset that runs after embedding:

```python
# Pseudocode
for node in newly_embedded_nodes:
    similar = qdrant.search(
        vector=node.embedding,
        limit=config.top_k_candidates,
        filter={"silo_id": silo_id}
    )
    
    for candidate in similar[:config.max_links_per_node]:
        if candidate.score >= config.similarity_threshold:
            if not edge_exists(node.id, candidate.id):
                create_weak_edge(node.id, candidate.id, candidate.score)
```

## Section 2: Configuration

**File:** `config/weak_links.yaml`

```yaml
weak_links:
  enabled: true
  
  # Ingest-time creation
  ingest:
    similarity_threshold: 0.75
    max_links_per_node: 5
    top_k_candidates: 10
    
  # Edge properties
  defaults:
    initial_weight_multiplier: 0.5
    speculative: true
    
  # Promotion thresholds
  promotion:
    min_weight: 0.6
    min_edge_heat: 0.3
    require_fact_endpoints: true
    
  # Pruning
  pruning:
    max_age_days: 30
    min_edge_heat: 0.1
    
  # Future (Approach C) - DO NOT ENABLE
  future:
    transitive_inference: false
    llm_judge: false
    active_learning: false
    cross_silo: false
```

Settings loaded via pydantic-settings, same pattern as existing config.

## Section 3: Edge Access Events

**Emit when:** Graph traversal follows an edge (depth > 0 in context_recall)

### New Function

```python
async def emit_edge_access_event(
    redis: RedisClient,
    silo_id: str,
    from_node: str,
    to_node: str,
    edge_type: str,
    traversal_context: str = "recall"  # recall|provenance|graph
) -> None:
    """Append edge access event to silo stream. Best-effort."""
    stream_key = f"silo:{silo_id}:edge_access_events"
    await redis.xadd(
        stream_key,
        {
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "context": traversal_context,
        },
        maxlen=ACCESS_STREAM_MAXLEN,
    )
```

### Call Sites

- `context_recall` with `depth > 0`
- Provenance queries (trace skill)
- Any graph walk that returns edge data

### Edge ID Generation

Deterministic ID from sorted node pair (stored as `r.id` property on the edge):
```python
def edge_id(from_node: str, to_node: str, edge_type: str) -> str:
    pair = tuple(sorted([from_node, to_node]))
    return str(uuid5(NAMESPACE, f"{pair[0]}:{pair[1]}:{edge_type}"))
```

This ensures idempotent edge creation and enables efficient updates by ID.

## Section 4: Edge Heat Computation

**New Dagster asset:** `edge_heat`

### Pattern (mirrors existing heat asset)

| Node heat (existing) | Edge heat (new) |
|---------------------|-----------------|
| `silo:{id}:access_events` | `silo:{id}:edge_access_events` |
| `:HeatCursor` singleton | `:EdgeHeatCursor` singleton |
| `MATCH (n {id: ...})` | `MATCH ()-[r {id: ...}]->()` |
| `n.heat_score, n.tier` | `r.edge_heat` |

### Asset Definition

```python
@dg.asset(
    name="edge_heat",
    partitions_def=silo_partitions,
    deps=["heat"],  # run after node heat
    description="Compute edge heat from traversal events",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "edge_heat"},
)
def edge_heat_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    ...
```

### Update Cypher

```cypher
UNWIND $updates AS u
MATCH ()-[r {id: u.edge_id}]->()
SET r.edge_heat = u.heat_score,
    r.heat_updated_at = $now
```

### Constants

- `EDGE_HEAT_HALF_LIFE_DAYS = 7` (same as node heat)
- `XREAD_COUNT = 10_000`

## Section 5: Custodian Promotion and Pruning

**New Dagster asset:** `weak_link_review`

Runs after heat assets complete. Separate from cluster-focused custodian visits.

### Asset Definition

```python
@dg.asset(
    name="weak_link_review",
    partitions_def=silo_partitions,
    deps=["heat", "edge_heat"],
    description="Promote high-signal weak links, prune unused ones",
    tags={"dagster/concurrency_key": "weak_link_review"},
)
def weak_link_review_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    ...
```

### Promotion Criteria

All must be true:
```python
edge.speculative == True
AND edge.weight >= config.promotion.min_weight        # 0.6
AND edge.edge_heat >= config.promotion.min_edge_heat  # 0.3
AND (not config.promotion.require_fact_endpoints 
     OR (from_node:Fact AND to_node:Fact))
```

### Promotion Query

```cypher
MATCH (a)-[r:RELATED_TO]->(b)
WHERE r.speculative = true
  AND r.silo_id = $silo_id
  AND r.weight >= $min_weight
  AND r.edge_heat >= $min_edge_heat
  AND ($require_facts = false OR (a:Fact AND b:Fact))
SET r.speculative = false,
    r.promoted_at = datetime(),
    r.promoted_by = 'custodian'
RETURN count(r) AS promoted
```

### Pruning Criteria

```python
edge.speculative == True
AND age(edge.created_at) > config.pruning.max_age_days  # 30
AND edge.edge_heat < config.pruning.min_edge_heat       # 0.1
```

### Pruning Query

```cypher
MATCH (a)-[r:RELATED_TO]->(b)
WHERE r.speculative = true
  AND r.silo_id = $silo_id
  AND r.created_at < datetime() - duration({days: $max_age_days})
  AND r.edge_heat < $min_edge_heat
DELETE r
RETURN count(r) AS pruned
```

## Section 6: Future Scope (Post-100 Users)

Deferred to Approach C. Revisit after 100 active users with usage data.

| Feature | Description | Implementation Trigger |
|---------|-------------|------------------------|
| Transitive inference | A->B, B->C creates weak A~C | Graph density justifies compute cost |
| LLM judge | Model validates ambiguous promotions | False-positive rate exceeds threshold |
| Active learning | Surface uncertain edges for agent confirmation | Agent interaction patterns stabilize |
| Cross-silo weak links | Link similar nodes across silos | Multi-tenant use cases emerge |

Config placeholders exist but are disabled.

## Implementation Plan

### Phase 1: Infrastructure
1. Add weak_links config schema
2. Create `emit_edge_access_event` function
3. Create `:EdgeHeatCursor` singleton pattern

### Phase 2: Ingest-time Creation
4. Extend embedding asset to query similar nodes
5. Create weak RELATED_TO edges with speculative flag
6. Add edge ID generation

### Phase 3: Signal Accumulation
7. Wire `emit_edge_access_event` into context_recall (depth > 0)
8. Create `edge_heat` Dagster asset
9. Test heat accumulation

### Phase 4: Review Cycle
10. Create `weak_link_review` Dagster asset
11. Implement promotion logic
12. Implement pruning logic
13. Add metrics/logging

### Phase 5: Validation
14. Integration tests for full cycle
15. Load test with realistic data
16. Tune thresholds based on results

## Success Criteria

- Weak links created during ingest (measurable via edge count)
- Edge heat accumulates on traversal (observable in Memgraph)
- High-signal edges promoted (speculative=false count increases)
- Unused edges pruned (total speculative edge count stabilizes)
- Query latency unchanged or improved (pre-computed vs runtime similarity)

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Fan-out explosion | Cap at max_links_per_node (5) |
| Noise from low-quality links | Pruning removes unused edges |
| Heat asset overhead | Batch processing, same pattern as node heat |
| False promotions | require_fact_endpoints flag, tunable thresholds |
