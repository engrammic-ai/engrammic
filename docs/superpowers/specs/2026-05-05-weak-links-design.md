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
    "embedding_model": "<model_version>",  # e.g., "jina-v3"
    "edge_heat": 0.0,
    "heat_updated_at": None
}
```

**Note:** `embedding_model` tracks which model produced the similarity score. On model upgrade, edges from old models should be purged or re-evaluated.

### Constraints

- Only between nodes in same silo
- Skip if explicit edge already exists between the pair
- Skip self-links
- Cap at max_links_per_node (default 5) to avoid fan-out explosion
- Minimum similarity threshold (default 0.75)

### Implementation

Extend embedding asset or create new `weak_link_creation` asset that runs after embedding:

```python
# Pseudocode - FIXED for race conditions and cap enforcement
for node in newly_embedded_nodes:
    # 1. Query existing weak link degree
    existing_degree = count_weak_links(node.id, silo_id)
    budget = max(0, config.max_links_per_node - existing_degree)
    
    if budget == 0:
        continue
    
    # 2. Search for similar nodes
    similar = qdrant.search(
        vector=node.embedding,
        limit=config.top_k_candidates,
        filter={"silo_id": silo_id}
    )
    
    # 3. Filter by threshold FIRST, then cap
    candidates = [c for c in similar if c.score >= config.similarity_threshold]
    candidates = candidates[:budget]
    
    # 4. Create edges using MERGE (idempotent, handles concurrent ingest)
    for candidate in candidates:
        # Always create edge in sorted order (a < b lexicographically)
        # This ensures symmetric edge_id regardless of which node is ingested first
        a, b = sorted([node.id, candidate.id])
        eid = edge_id(a, b, "RELATED_TO")
        
        merge_weak_edge(
            from_node=a,
            to_node=b,
            edge_id=eid,
            weight=candidate.score * config.initial_weight_multiplier,
            embedding_model=config.embedding_model_version
        )
```

### WeakLink Creation Cypher

Use MERGE on the WeakLink node for idempotency:
```cypher
MATCH (a {id: $from_id, silo_id: $silo_id})
MATCH (b {id: $to_id, silo_id: $silo_id})
MERGE (w:WeakLink {id: $link_id, silo_id: $silo_id})
ON CREATE SET
    w.weight = $weight,
    w.speculative = true,
    w.created_at = datetime(),
    w.source = 'embedding_similarity',
    w.embedding_model = $embedding_model,
    w.edge_heat = 0.0,
    w.from_node = $from_id,
    w.to_node = $to_id
MERGE (a)-[:SOURCE_OF]->(w)
MERGE (w)-[:TARGETS]->(b)
RETURN w.id AS created
```

### Required Index

```cypher
CREATE INDEX ON :WeakLink(id);
CREATE INDEX ON :WeakLink(silo_id);
CREATE INDEX ON :WeakLink(speculative);
```

### Degree Check Query

```cypher
MATCH (n {id: $node_id, silo_id: $silo_id})-[r:RELATED_TO]-()
WHERE r.speculative = true
RETURN count(r) AS degree
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
# Counter for observability
EDGE_ACCESS_EVENTS_DROPPED = Counter(
    "edge_access_events_dropped_total",
    "Edge access events dropped due to Redis errors",
    ["silo_id"]
)

async def emit_edge_access_event(
    redis: RedisClient,
    silo_id: str,
    from_node: str,
    to_node: str,
    edge_type: str,
    traversal_context: str = "recall"  # recall|provenance|graph
) -> None:
    """Append edge access event to silo stream. Best-effort, never raises.
    
    Failures are logged at WARN and counted via EDGE_ACCESS_EVENTS_DROPPED.
    Callers should NOT wrap this in try/except - it handles errors internally.
    
    Note: Heat computed from these events is a LOWER BOUND, not exact count.
    Dropped events mean some traversals are not reflected in edge_heat.
    """
    try:
        stream_key = f"silo:{silo_id}:edge_access_events"
        await asyncio.wait_for(
            redis.xadd(
                stream_key,
                {
                    "from_node": from_node,
                    "to_node": to_node,
                    "edge_type": edge_type,
                    "context": traversal_context,
                },
                maxlen=ACCESS_STREAM_MAXLEN,
            ),
            timeout=1.0  # 1s timeout - don't block reads
        )
    except Exception as e:
        EDGE_ACCESS_EVENTS_DROPPED.labels(silo_id=silo_id).inc()
        logger.warning(
            "edge_access_event_dropped",
            silo_id=silo_id,
            from_node=from_node,
            to_node=to_node,
            error=str(e)
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

**Directionality invariant:** Edges are ALWAYS created in sorted order (lexicographically smaller node ID first). This means:
- `edge_id("node-A", "node-B", "RELATED_TO") == edge_id("node-B", "node-A", "RELATED_TO")`
- The edge `A->B` is created, never `B->A`
- For traversal purposes, RELATED_TO is treated as **undirected** (query both directions)

This ensures idempotent edge creation and enables efficient updates by ID.

## Section 4: Edge Heat Computation

**New Dagster asset:** `edge_heat`

### Schema Decision: Reified WeakLink Nodes

**Problem:** Memgraph edge property indexes don't work with named parameters. `MATCH ()-[r {id: $edge_id}]->()` is always a full scan.

**Solution:** Reify weak links as intermediate nodes:

```
(A)-[:SOURCE_OF]->(WeakLink {id, weight, speculative, ...})-[:TARGETS]->(B)
```

This enables:
- Standard node index: `CREATE INDEX ON :WeakLink(id)`
- Parameterized queries work: `MATCH (w:WeakLink {id: $id})`
- All existing node heat patterns apply directly

**Docker-compose update required:**
```yaml
command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
```

### Pattern (mirrors existing heat asset)

| Node heat (existing) | Edge heat (new) |
|---------------------|-----------------|
| `silo:{id}:access_events` | `silo:{id}:edge_access_events` |
| `:HeatCursor` singleton | `:EdgeHeatCursor` singleton |
| `MATCH (n {id: ...})` | `MATCH (w:WeakLink {id: ...})` |
| `n.heat_score, n.tier` | `w.edge_heat` |

### Asset Definition

```python
@dg.asset(
    name="edge_heat",
    partitions_def=silo_partitions,
    deps=["heat"],  # run after node heat
    description="Compute edge heat from traversal events",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    # No global concurrency key - allow parallel execution across silos
)
def edge_heat_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    ...
```

**Note:** No `dagster/concurrency_key` - silos run in parallel. If resource contention becomes an issue, add per-silo key: `f"edge_heat:{context.partition_key}"`

### Update Cypher

```cypher
UNWIND $updates AS u
MATCH (w:WeakLink {id: u.link_id, silo_id: $silo_id})
SET w.edge_heat = u.heat_score,
    w.heat_updated_at = $now
```

Uses the `:WeakLink(id)` index - no full scan.

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
    description="Promote high-signal weak links, prune unused ones, demote stale promoted links",
    # No global concurrency key - silos run in parallel
)
def weak_link_review_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    # 1. Promote eligible speculative edges
    # 2. Prune old unused speculative edges
    # 3. Demote promoted edges whose endpoints were superseded
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
MATCH (a)-[:SOURCE_OF]->(w:WeakLink)-[:TARGETS]->(b)
WHERE w.speculative = true
  AND w.silo_id = $silo_id
  AND w.weight >= $min_weight
  AND w.edge_heat >= $min_edge_heat
  AND ($require_facts = false OR (a:Fact AND b:Fact))
SET w.speculative = false,
    w.promoted_at = datetime(),
    w.promoted_by = 'custodian'
RETURN count(w) AS promoted
```

### Pruning Criteria

```python
edge.speculative == True
AND age(edge.created_at) > config.pruning.max_age_days  # 30
AND edge.edge_heat < config.pruning.min_edge_heat       # 0.1
```

### Pruning Query

```cypher
MATCH (a)-[s:SOURCE_OF]->(w:WeakLink)-[t:TARGETS]->(b)
WHERE w.speculative = true
  AND w.silo_id = $silo_id
  AND w.created_at < datetime() - duration({days: $max_age_days})
  AND w.edge_heat < $min_edge_heat
DELETE s, t, w
RETURN count(w) AS pruned
```

**Note on pruning timing:** With `EDGE_HEAT_HALF_LIFE_DAYS = 7` and `max_age_days = 30`, heat decays to ~5% of peak after 30 days. The `min_edge_heat: 0.1` threshold means edges with any early activity will be pruned by heat decay before the age limit kicks in. The age limit is a backstop for edges with zero activity, not a grace period.

### Demotion (Rollback for False Promotions)

Promoted edges (`speculative = false`) can become invalid when:
- An endpoint node is superseded
- An endpoint Fact is retracted
- Embedding model is upgraded

**Demotion Query:**
```cypher
// Demote weak links where an endpoint was superseded
MATCH (a)-[:SOURCE_OF]->(w:WeakLink)-[:TARGETS]->(b)
WHERE w.speculative = false
  AND w.silo_id = $silo_id
  AND (a.superseded = true OR b.superseded = true)
SET w.speculative = true,
    w.demoted_at = datetime(),
    w.demoted_reason = 'endpoint_superseded'
RETURN count(w) AS demoted
```

**Embedding model migration:**
```cypher
// Mark weak links from old embedding model for re-evaluation
MATCH (w:WeakLink)
WHERE w.silo_id = $silo_id
  AND w.embedding_model <> $current_model
SET w.speculative = true,
    w.demoted_at = datetime(),
    w.demoted_reason = 'model_upgrade'
RETURN count(w) AS demoted
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
| Fan-out explosion | Cap at max_links_per_node (5), check existing degree |
| Noise from low-quality links | Pruning removes unused edges |
| Heat asset overhead | Batch processing, same pattern as node heat |
| False promotions | require_fact_endpoints flag, tunable thresholds, demotion path |
| Edge property index perf | Reified WeakLink nodes with standard index |
| Race conditions on create | MERGE with deterministic ID |
| Embedding model drift | embedding_model property + migration queries |
| Redis failures | Best-effort emit with metrics, heat is lower bound |

## Schema Changes Required

1. **New node label:** `:WeakLink`
2. **New edge types:** `:SOURCE_OF`, `:TARGETS`
3. **Indexes:**
   ```cypher
   CREATE INDEX ON :WeakLink(id);
   CREATE INDEX ON :WeakLink(silo_id);
   CREATE INDEX ON :WeakLink(speculative);
   ```
4. **Docker-compose:** Add `--storage-properties-on-edges=true`
