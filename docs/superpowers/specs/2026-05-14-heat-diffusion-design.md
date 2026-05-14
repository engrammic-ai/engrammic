# Heat Diffusion for Lazy Materialization

**Date:** 2026-05-14  
**Status:** Draft  
**Author:** Claude + User

## Overview

Add heat propagation through the graph so nodes close to hot nodes become warmer, enabling smarter retrieval ranking and background pre-warming of likely-needed computations.

This builds on the existing `heat_asset` which tracks direct access, adding a diffusion layer that propagates heat to neighbors based on edge type and edge heat.

## Goals

1. **Smarter retrieval ranking:** Nodes near hot nodes rank higher even if never directly accessed
2. **Background pre-warming:** Prioritize expensive computations (weak links, belief synthesis) for warming nodes
3. **Foundation for lazy compute:** Materialization levels enable future deferred computation (V2)

## Non-Goals (V1.5)

- Lazy computation on read path (latency risk)
- Incremental/delta-based diffusion (premature optimization)
- Learnable edge weights (V3)

## Data Model

### New Node Properties

| Property | Type | Description |
|----------|------|-------------|
| `propagated_heat` | float | Heat received from neighbors (0.0-1.0) |
| `effective_heat` | float | `heat_score + propagated_heat`, clamped to 1.0 |
| `materialization_level` | string | `FULL` / `WARM` / `STRUCTURE` / `MINIMAL` |
| `diffusion_updated_at` | ISO timestamp | Last diffusion run that touched this node |
| `prewarmed_at` | ISO timestamp | Last time pre-warming ran for this node |

### Materialization Thresholds

| Level | effective_heat | Meaning |
|-------|----------------|---------|
| FULL | > 0.6 | Hot path, pre-warm everything |
| WARM | 0.25 - 0.6 | Likely accessed, prioritize background jobs |
| STRUCTURE | 0.05 - 0.25 | Occasionally accessed |
| MINIMAL | < 0.05 | Cold, defer expensive work |

### Edge Type Propagation Weights

Starting guesses based on semantic importance. Will be tuned based on instrumentation data.

| Edge Type | Weight | Reasoning |
|-----------|--------|-----------|
| CONTRADICTS | 0.95 | Core to self-correction thesis |
| SUPPORTS | 0.90 | Evidence chains are core to provenance |
| DEPENDS_ON | 0.85 | Structural dependencies |
| CITES | 0.80 | Provenance, one step removed |
| CAUSES | 0.80 | Causal understanding |
| DERIVES_FROM | 0.75 | Derivation chains |
| CORROBORATES | 0.70 | Additional evidence, not primary |
| PREVENTS | 0.70 | Negative relationships |
| RELATED_TO | 0.40 | Weak association, low signal |

## Algorithm

### Approach: Python BFS with Batched Writes

Chosen over single Cypher query for:
- Configurability (edge weights in Python config)
- Debuggability (can log each propagation step)
- Flexibility for future enhancements

### Pseudocode

```python
async def diffuse_heat(store, silo_id, config) -> DiffusionResult:
    # 1. Decay existing propagated heat
    await decay_propagated_heat(store, silo_id, config.propagated_heat_decay)
    
    # 2. Fetch all hot nodes
    hot_nodes = await fetch_hot_nodes(store, silo_id, config.hot_threshold)
    
    # 3. BFS from each hot node
    propagation_map: dict[str, float] = {}
    edge_traversals: Counter[str] = Counter()
    
    for hot_node in hot_nodes:
        visited = {hot_node.id}
        frontier = [(hot_node.id, hot_node.heat_score, 0)]
        
        while frontier:
            current_id, current_heat, depth = frontier.pop(0)
            if depth >= config.max_depth:
                continue
            
            neighbors = await fetch_neighbors(store, current_id, silo_id)
            
            for edge in neighbors:
                if edge.target_id in visited:
                    continue
                
                edge_weight = config.edge_weights.get(edge.type, 0.4)
                edge_heat = edge.heat or 0.5
                propagated = current_heat * config.hop_decay * edge_weight * edge_heat
                
                if propagated < config.min_threshold:
                    continue
                
                propagation_map[edge.target_id] = max(
                    propagation_map.get(edge.target_id, 0),
                    propagated
                )
                
                edge_traversals[edge.type] += 1
                visited.add(edge.target_id)
                frontier.append((edge.target_id, propagated, depth + 1))
    
    # 4. Batch write
    await batch_update_propagated_heat(store, silo_id, propagation_map)
    
    return DiffusionResult(
        hot_nodes=len(hot_nodes),
        nodes_updated=len(propagation_map),
        edge_traversals=dict(edge_traversals),
    )
```

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `hot_threshold` | 0.5 | Minimum heat_score to be a propagation source |
| `hop_decay` | 0.7 | Heat multiplier per hop |
| `max_depth` | 3 | Maximum BFS depth |
| `min_threshold` | 0.01 | Stop propagating below this |
| `max_propagation_per_source` | 500 | Cap nodes visited per hot source |
| `propagated_heat_decay` | 0.8 | Per-run decay of existing propagated_heat |

### Validation Criteria

Sanity checks after each run:
1. `max(effective_heat) <= 1.0` for all nodes
2. `sum(propagated_heat)` decreases over time if no new accesses
3. Nodes 3+ hops from any hot node have `propagated_heat < 0.1`
4. Directly accessed nodes have higher effective_heat than neighbors

## Dagster Assets

### heat_diffusion

```python
@dg.asset(
    name="heat_diffusion",
    deps=["heat"],
    partitions_def=silo_partitions,
    description="Propagate heat from hot nodes to neighbors via BFS",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "heat_diffusion"},
)
def heat_diffusion_asset(context, memgraph):
    ...
```

### prewarm_sweep

```python
@dg.asset(
    name="prewarm_sweep",
    deps=["heat_diffusion"],
    partitions_def=silo_partitions,
    description="Trigger background work for nodes transitioning to WARM/FULL",
)
def prewarm_sweep_asset(context, memgraph):
    ...
```

### Schedule

| Asset | Frequency | Order | Dependency |
|-------|-----------|-------|------------|
| `heat` | Hourly | 1 | None |
| `edge_heat` | Hourly | 2 | None |
| `heat_diffusion` | Hourly | 3 | After `heat` |
| `prewarm_sweep` | Hourly | 4 | After `heat_diffusion` |

## Pre-warming Integration

### Jobs Affected

| Job | How heat affects it | Mechanism |
|-----|---------------------|-----------|
| `weak_link_creation` | WARM/FULL nodes get links created first | Priority queue ordered by effective_heat |
| `belief_synthesis` | Clusters containing HOT facts get synthesized first | Cluster priority = max(fact.effective_heat) |
| `llm_pattern_detection` | Skip MINIMAL nodes entirely | Filter predicate in asset query |

### Logic

```python
async def prewarm_sweep(store, silo_id):
    warming_nodes = await fetch_warming_nodes(store, silo_id)
    
    for node in warming_nodes:
        if not node.has_weak_links:
            await enqueue_weak_link_creation(node.id, priority=node.effective_heat)
        
        if node.cluster_id:
            await bump_cluster_priority(node.cluster_id, node.effective_heat)
    
    await mark_prewarmed(store, silo_id, [n.id for n in warming_nodes])
```

## Retrieval Integration

Change ranking to use `effective_heat` instead of `heat_score`:

```python
# Before
heat = node.heat_score or 0.5

# After  
heat = node.effective_heat or node.heat_score or 0.5
```

No other retrieval changes for V1.5.

## Configuration

### File: config/diffusion.yaml

```yaml
diffusion:
  enabled: true
  hot_threshold: 0.5
  hop_decay: 0.7
  max_depth: 3
  min_threshold: 0.01
  max_propagation_per_source: 500
  propagated_heat_decay: 0.8

  thresholds:
    full: 0.6
    warm: 0.25
    structure: 0.05

  edge_weights:
    CONTRADICTS: 0.95
    SUPPORTS: 0.90
    DEPENDS_ON: 0.85
    CITES: 0.80
    CAUSES: 0.80
    DERIVES_FROM: 0.75
    CORROBORATES: 0.70
    PREVENTS: 0.70
    RELATED_TO: 0.40

prewarm:
  enabled: true
  weak_links_priority_boost: 1.5
  skip_minimal_pattern_detection: true
```

### Precedence

1. Environment variables (highest)
2. `config/diffusion.yaml`
3. Code defaults (lowest)

## Observability

### Structured Logging

```python
logger.info(
    "heat_diffusion_complete",
    silo_id=silo_id,
    hot_nodes=result.hot_nodes,
    nodes_updated=result.nodes_updated,
    edge_traversals=result.edge_traversals,
    duration_s=duration,
)
```

### Dagster Metadata

```python
metadata={
    "hot_nodes": dg.MetadataValue.int(result.hot_nodes),
    "nodes_updated": dg.MetadataValue.int(result.nodes_updated),
    "edge_traversals": dg.MetadataValue.json(result.edge_traversals),
    "distribution": dg.MetadataValue.json({
        "FULL": counts["FULL"],
        "WARM": counts["WARM"],
        "STRUCTURE": counts["STRUCTURE"],
        "MINIMAL": counts["MINIMAL"],
    }),
}
```

### OTEL Spans

```python
with tracer.start_as_current_span("heat_diffusion") as span:
    span.set_attribute("silo_id", silo_id)
    span.set_attribute("hot_nodes", len(hot_nodes))
    span.set_attribute("nodes_updated", len(propagation_map))
```

### Edge Weight Tuning

Track `edge_traversals` over time to understand which edge types are actually used. Adjust weights based on real traversal patterns after 2-4 weeks of production data.

## Performance Targets

| Silo Size | Target Runtime |
|-----------|----------------|
| 100s nodes | < 5 seconds |
| 10,000+ nodes | < 60 seconds |

## Future Work (V2+)

- Lazy computation on read path for MINIMAL nodes
- Delta-based incremental diffusion
- Learnable edge weights based on traversal patterns
- Per-silo weight overrides

## References

- [LazyGraphRAG](https://www.microsoft.com/en-us/research/blog/lazygraphrag-setting-a-new-standard-for-quality-and-cost/)
- [Personalized PageRank (VLDB)](https://www.vldb.org/pvldb/vol4/p173-bahmani.pdf)
- Research notes: `~/.claude-bits/engrammic/2026-05-14-jepa-engram-discussion.md`
- Notion: Personal Notes > Research: JEPA, Engram, Heat Diffusion
