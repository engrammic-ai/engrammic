# Heat Diffusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add heat propagation through the graph so nodes near hot nodes become warmer, enabling smarter retrieval ranking and background pre-warming.

**Architecture:** Python BFS from hot nodes with batched subgraph fetch (single Cypher query), in-memory adjacency traversal, batched writes. Edge type weights configurable via YAML. Runs as hourly Dagster asset after existing `heat` asset.

**Tech Stack:** Python 3.12, Dagster, Memgraph (Cypher), YAML config, structlog, OpenTelemetry

**Spec:** `docs/superpowers/specs/2026-05-14-heat-diffusion-design.md`

---

## File Structure

| File | Purpose |
|------|---------|
| `config/diffusion.yaml` | Edge weights, thresholds, parameters |
| `src/context_service/config/diffusion.py` | Load YAML config, Pydantic models |
| `src/context_service/signals/diffusion.py` | Core BFS algorithm, subgraph fetch |
| `src/context_service/pipelines/assets/heat_diffusion.py` | Dagster asset |
| `src/context_service/pipelines/assets/prewarm_sweep.py` | Pre-warming asset |
| `tests/signals/test_diffusion.py` | Unit tests for diffusion algorithm |
| `tests/pipelines/test_heat_diffusion.py` | Integration tests for assets |

**Files to modify:**
- `src/context_service/services/context.py` - Use `effective_heat` in ranking
- `src/context_service/pipelines/assets/__init__.py` - Export new assets

---

## Task 1: Configuration

**Files:**
- Create: `config/diffusion.yaml`
- Create: `src/context_service/config/diffusion.py`
- Test: `tests/config/test_diffusion_config.py`

- [ ] **Step 1.1: Create YAML config file**

```yaml
# config/diffusion.yaml
diffusion:
  enabled: true
  hot_threshold: 0.5
  hop_decay: 0.7
  max_depth: 3
  min_threshold: 0.01
  max_hot_nodes: 200
  propagated_heat_decay: 0.8

  thresholds:
    full: 0.66
    warm: 0.33
    structure: 0.1

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

- [ ] **Step 1.2: Write failing test for config loading**

```python
# tests/config/test_diffusion_config.py
import pytest
from context_service.config.diffusion import load_diffusion_config, DiffusionConfig

def test_load_diffusion_config_defaults():
    config = load_diffusion_config()
    assert config.enabled is True
    assert config.hot_threshold == 0.5
    assert config.hop_decay == 0.7
    assert config.max_depth == 3
    assert config.edge_weights["CONTRADICTS"] == 0.95
    assert config.edge_weights["RELATED_TO"] == 0.40

def test_materialization_level():
    config = load_diffusion_config()
    assert config.get_materialization_level(0.7) == "FULL"
    assert config.get_materialization_level(0.5) == "WARM"
    assert config.get_materialization_level(0.2) == "STRUCTURE"
    assert config.get_materialization_level(0.05) == "MINIMAL"
```

- [ ] **Step 1.3: Run test to verify it fails**

Run: `uv run pytest tests/config/test_diffusion_config.py -v`
Expected: FAIL with "No module named 'context_service.config.diffusion'"

- [ ] **Step 1.4: Implement config module**

```python
# src/context_service/config/diffusion.py
"""Heat diffusion configuration loaded from YAML with env overrides."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class DiffusionThresholds(BaseModel):
    full: float = 0.66
    warm: float = 0.33
    structure: float = 0.1


class DiffusionConfig(BaseModel):
    enabled: bool = True
    hot_threshold: float = 0.5
    hop_decay: float = 0.7
    max_depth: int = 3
    min_threshold: float = 0.01
    max_hot_nodes: int = 200
    propagated_heat_decay: float = 0.8
    thresholds: DiffusionThresholds = Field(default_factory=DiffusionThresholds)
    edge_weights: dict[str, float] = Field(default_factory=lambda: {
        "CONTRADICTS": 0.95,
        "SUPPORTS": 0.90,
        "DEPENDS_ON": 0.85,
        "CITES": 0.80,
        "CAUSES": 0.80,
        "DERIVES_FROM": 0.75,
        "CORROBORATES": 0.70,
        "PREVENTS": 0.70,
        "RELATED_TO": 0.40,
    })

    def get_materialization_level(self, effective_heat: float) -> str:
        if effective_heat >= self.thresholds.full:
            return "FULL"
        if effective_heat >= self.thresholds.warm:
            return "WARM"
        if effective_heat >= self.thresholds.structure:
            return "STRUCTURE"
        return "MINIMAL"


class PrewarmConfig(BaseModel):
    enabled: bool = True
    weak_links_priority_boost: float = 1.5
    skip_minimal_pattern_detection: bool = True


def _find_config_file() -> Path | None:
    candidates = [
        Path(__file__).parent.parent.parent.parent / "config" / "diffusion.yaml",
        Path("config/diffusion.yaml"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


@lru_cache
def load_diffusion_config() -> DiffusionConfig:
    config_path = _find_config_file()
    if config_path is not None:
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return DiffusionConfig(**data.get("diffusion", {}))
    return DiffusionConfig()


@lru_cache
def load_prewarm_config() -> PrewarmConfig:
    config_path = _find_config_file()
    if config_path is not None:
        with open(config_path) as f:
            data = yaml.safe_load(f)
        return PrewarmConfig(**data.get("prewarm", {}))
    return PrewarmConfig()


__all__ = [
    "DiffusionConfig",
    "DiffusionThresholds",
    "PrewarmConfig",
    "load_diffusion_config",
    "load_prewarm_config",
]
```

- [ ] **Step 1.5: Run test to verify it passes**

Run: `uv run pytest tests/config/test_diffusion_config.py -v`
Expected: PASS

- [ ] **Step 1.6: Commit**

```bash
git add config/diffusion.yaml src/context_service/config/diffusion.py tests/config/test_diffusion_config.py
git commit -m "feat(diffusion): add config module with YAML loading"
```

---

## Task 2: Diffusion Algorithm Core

**Files:**
- Create: `src/context_service/signals/diffusion.py`
- Test: `tests/signals/test_diffusion.py`

- [ ] **Step 2.1: Write failing test for subgraph edge model**

```python
# tests/signals/test_diffusion.py
import pytest
from context_service.signals.diffusion import SubgraphEdge, build_adjacency_list

def test_subgraph_edge_model():
    edge = SubgraphEdge(
        source_id="node-a",
        target_id="node-b",
        edge_type="SUPPORTS",
        edge_heat=0.8,
    )
    assert edge.source_id == "node-a"
    assert edge.target_id == "node-b"
    assert edge.edge_type == "SUPPORTS"
    assert edge.edge_heat == 0.8

def test_build_adjacency_list():
    edges = [
        SubgraphEdge("a", "b", "SUPPORTS", 0.5),
        SubgraphEdge("a", "c", "CITES", 0.6),
        SubgraphEdge("b", "c", "RELATED_TO", 0.3),
    ]
    adj = build_adjacency_list(edges)
    
    assert len(adj["a"]) == 2
    assert len(adj["b"]) == 2  # b->c and b->a (bidirectional)
    assert len(adj["c"]) == 2  # c->a and c->b (bidirectional)
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `uv run pytest tests/signals/test_diffusion.py::test_subgraph_edge_model -v`
Expected: FAIL with "No module named 'context_service.signals.diffusion'"

- [ ] **Step 2.3: Implement data models and adjacency builder**

```python
# src/context_service/signals/diffusion.py
"""Heat diffusion algorithm: BFS propagation from hot nodes."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from context_service.config.diffusion import DiffusionConfig
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


@dataclass
class SubgraphEdge:
    source_id: str
    target_id: str
    edge_type: str
    edge_heat: float | None


@dataclass
class HotNode:
    id: str
    heat_score: float


@dataclass
class DiffusionResult:
    hot_nodes: int
    nodes_updated: int
    edge_traversals: dict[str, int]
    propagation_map: dict[str, float] = field(default_factory=dict)


def build_adjacency_list(
    edges: list[SubgraphEdge],
) -> dict[str, list[SubgraphEdge]]:
    """Build bidirectional adjacency list from edges."""
    adj: dict[str, list[SubgraphEdge]] = defaultdict(list)
    for edge in edges:
        adj[edge.source_id].append(edge)
        reverse = SubgraphEdge(
            source_id=edge.target_id,
            target_id=edge.source_id,
            edge_type=edge.edge_type,
            edge_heat=edge.edge_heat,
        )
        adj[edge.target_id].append(reverse)
    return dict(adj)
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `uv run pytest tests/signals/test_diffusion.py -v`
Expected: PASS

- [ ] **Step 2.5: Write failing test for BFS propagation**

```python
# tests/signals/test_diffusion.py (append)

def test_propagate_heat_bfs():
    from context_service.signals.diffusion import propagate_heat_bfs, SubgraphEdge, HotNode
    from context_service.config.diffusion import DiffusionConfig
    
    config = DiffusionConfig(hop_decay=0.7, min_threshold=0.01, max_depth=2)
    
    edges = [
        SubgraphEdge("hot", "neighbor1", "SUPPORTS", 0.8),
        SubgraphEdge("neighbor1", "neighbor2", "CITES", 0.6),
    ]
    adjacency = build_adjacency_list(edges)
    
    hot_nodes = [HotNode(id="hot", heat_score=1.0)]
    
    result = propagate_heat_bfs(hot_nodes, adjacency, config)
    
    assert "neighbor1" in result.propagation_map
    assert "neighbor2" in result.propagation_map
    
    # neighbor1: 1.0 * 0.7 * 0.9 (SUPPORTS) * 0.8 (edge_heat) = 0.504
    assert 0.5 < result.propagation_map["neighbor1"] < 0.51
    
    # neighbor2: 0.504 * 0.7 * 0.8 (CITES) * 0.6 = 0.169
    assert 0.16 < result.propagation_map["neighbor2"] < 0.18
    
    assert result.edge_traversals["SUPPORTS"] == 1
    assert result.edge_traversals["CITES"] == 1
```

- [ ] **Step 2.6: Run test to verify it fails**

Run: `uv run pytest tests/signals/test_diffusion.py::test_propagate_heat_bfs -v`
Expected: FAIL with "cannot import name 'propagate_heat_bfs'"

- [ ] **Step 2.7: Implement BFS propagation**

```python
# src/context_service/signals/diffusion.py (append)

def propagate_heat_bfs(
    hot_nodes: list[HotNode],
    adjacency: dict[str, list[SubgraphEdge]],
    config: DiffusionConfig,
) -> DiffusionResult:
    """Run BFS from hot nodes, propagating heat through edges."""
    propagation_map: dict[str, float] = {}
    edge_traversals: Counter[str] = Counter()
    
    for hot_node in hot_nodes:
        visited: set[str] = {hot_node.id}
        frontier: list[tuple[str, float, int]] = [(hot_node.id, hot_node.heat_score, 0)]
        
        while frontier:
            current_id, current_heat, depth = frontier.pop(0)
            
            if depth >= config.max_depth:
                continue
            
            for edge in adjacency.get(current_id, []):
                if edge.target_id in visited:
                    continue
                
                edge_weight = config.edge_weights.get(edge.edge_type, 0.4)
                edge_heat = edge.edge_heat if edge.edge_heat is not None else 0.5
                propagated = current_heat * config.hop_decay * edge_weight * edge_heat
                
                if propagated < config.min_threshold:
                    continue
                
                propagation_map[edge.target_id] = max(
                    propagation_map.get(edge.target_id, 0.0),
                    propagated,
                )
                
                edge_traversals[edge.edge_type] += 1
                visited.add(edge.target_id)
                frontier.append((edge.target_id, propagated, depth + 1))
    
    return DiffusionResult(
        hot_nodes=len(hot_nodes),
        nodes_updated=len(propagation_map),
        edge_traversals=dict(edge_traversals),
        propagation_map=propagation_map,
    )
```

- [ ] **Step 2.8: Run test to verify it passes**

Run: `uv run pytest tests/signals/test_diffusion.py::test_propagate_heat_bfs -v`
Expected: PASS

- [ ] **Step 2.9: Commit**

```bash
git add src/context_service/signals/diffusion.py tests/signals/test_diffusion.py
git commit -m "feat(diffusion): implement BFS propagation algorithm"
```

---

## Task 3: Database Queries

**Files:**
- Modify: `src/context_service/signals/diffusion.py`
- Test: `tests/signals/test_diffusion.py`

- [ ] **Step 3.1: Add Cypher query constants**

```python
# src/context_service/signals/diffusion.py (add after imports)

FETCH_HOT_NODES_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.heat_score >= $hot_threshold
RETURN n.id AS id, n.heat_score AS heat_score
ORDER BY n.heat_score DESC
LIMIT $limit
"""

FETCH_SUBGRAPH_QUERY = """
MATCH (hot {silo_id: $silo_id})
WHERE hot.id IN $hot_node_ids
MATCH path = (hot)-[r*1..3]-(neighbor)
WHERE neighbor.silo_id = $silo_id
UNWIND relationships(path) AS rel
WITH DISTINCT startNode(rel) AS src, endNode(rel) AS dst, rel
RETURN src.id AS source_id, dst.id AS target_id,
       type(rel) AS edge_type, rel.edge_heat AS edge_heat
"""

DECAY_PROPAGATED_HEAT_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.propagated_heat IS NOT NULL
SET n.propagated_heat = n.propagated_heat * $decay_factor
"""

UPDATE_PROPAGATED_HEAT_QUERY = """
UNWIND $updates AS u
MATCH (n {id: u.node_id, silo_id: $silo_id})
SET n.propagated_heat = u.propagated_heat,
    n.effective_heat = CASE 
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat > 1.0 THEN 1.0
        ELSE coalesce(n.heat_score, 0) + u.propagated_heat
    END,
    n.materialization_level = CASE
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $full_threshold THEN 'FULL'
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $warm_threshold THEN 'WARM'
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $structure_threshold THEN 'STRUCTURE'
        ELSE 'MINIMAL'
    END,
    n.diffusion_updated_at = $now
"""

COUNT_MATERIALIZATION_LEVELS_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.materialization_level IS NOT NULL
RETURN n.materialization_level AS level, count(*) AS count
"""
```

- [ ] **Step 3.2: Add async database functions**

```python
# src/context_service/signals/diffusion.py (append)

async def fetch_hot_nodes(
    store: HyperGraphStore,
    silo_id: str,
    hot_threshold: float,
    limit: int,
) -> list[HotNode]:
    """Fetch nodes with heat_score >= threshold."""
    rows = await store.execute_query(
        FETCH_HOT_NODES_QUERY,
        {"silo_id": silo_id, "hot_threshold": hot_threshold, "limit": limit},
    )
    return [HotNode(id=row["id"], heat_score=float(row["heat_score"])) for row in rows]


async def fetch_subgraph(
    store: HyperGraphStore,
    silo_id: str,
    hot_node_ids: list[str],
    max_depth: int,
) -> list[SubgraphEdge]:
    """Fetch all edges within max_depth of hot nodes."""
    if not hot_node_ids:
        return []
    
    query = FETCH_SUBGRAPH_QUERY.replace("*1..3", f"*1..{max_depth}")
    rows = await store.execute_query(
        query,
        {"silo_id": silo_id, "hot_node_ids": hot_node_ids},
    )
    return [
        SubgraphEdge(
            source_id=row["source_id"],
            target_id=row["target_id"],
            edge_type=row["edge_type"],
            edge_heat=float(row["edge_heat"]) if row["edge_heat"] is not None else None,
        )
        for row in rows
    ]


async def decay_propagated_heat(
    store: HyperGraphStore,
    silo_id: str,
    decay_factor: float,
) -> None:
    """Decay existing propagated heat values."""
    await store.execute_write(
        DECAY_PROPAGATED_HEAT_QUERY,
        {"silo_id": silo_id, "decay_factor": decay_factor},
    )


async def batch_update_propagated_heat(
    store: HyperGraphStore,
    silo_id: str,
    propagation_map: dict[str, float],
    config: DiffusionConfig,
) -> None:
    """Batch update propagated_heat, effective_heat, and materialization_level."""
    from datetime import UTC, datetime
    
    if not propagation_map:
        return
    
    updates = [
        {"node_id": node_id, "propagated_heat": heat}
        for node_id, heat in propagation_map.items()
    ]
    
    await store.execute_write(
        UPDATE_PROPAGATED_HEAT_QUERY,
        {
            "silo_id": silo_id,
            "updates": updates,
            "full_threshold": config.thresholds.full,
            "warm_threshold": config.thresholds.warm,
            "structure_threshold": config.thresholds.structure,
            "now": datetime.now(UTC).isoformat(),
        },
    )


async def get_materialization_distribution(
    store: HyperGraphStore,
    silo_id: str,
) -> dict[str, int]:
    """Get count of nodes per materialization level."""
    rows = await store.execute_query(
        COUNT_MATERIALIZATION_LEVELS_QUERY,
        {"silo_id": silo_id},
    )
    return {row["level"]: int(row["count"]) for row in rows}
```

- [ ] **Step 3.3: Add main diffuse_heat function**

```python
# src/context_service/signals/diffusion.py (append)

async def diffuse_heat(
    store: HyperGraphStore,
    silo_id: str,
    config: DiffusionConfig,
) -> DiffusionResult:
    """Main entry point: propagate heat from hot nodes to neighbors."""
    
    # 1. Decay existing propagated heat
    await decay_propagated_heat(store, silo_id, config.propagated_heat_decay)
    
    # 2. Fetch hot nodes
    hot_nodes = await fetch_hot_nodes(
        store, silo_id, config.hot_threshold, config.max_hot_nodes
    )
    
    if not hot_nodes:
        logger.info("heat_diffusion_no_hot_nodes", silo_id=silo_id)
        return DiffusionResult(hot_nodes=0, nodes_updated=0, edge_traversals={})
    
    # 3. Fetch subgraph
    subgraph = await fetch_subgraph(
        store, silo_id, [n.id for n in hot_nodes], config.max_depth
    )
    
    if not subgraph:
        logger.info("heat_diffusion_no_edges", silo_id=silo_id, hot_nodes=len(hot_nodes))
        return DiffusionResult(hot_nodes=len(hot_nodes), nodes_updated=0, edge_traversals={})
    
    # 4. Build adjacency and run BFS
    adjacency = build_adjacency_list(subgraph)
    result = propagate_heat_bfs(hot_nodes, adjacency, config)
    
    # 5. Batch update
    await batch_update_propagated_heat(store, silo_id, result.propagation_map, config)
    
    logger.info(
        "heat_diffusion_complete",
        silo_id=silo_id,
        hot_nodes=result.hot_nodes,
        nodes_updated=result.nodes_updated,
        edge_traversals=result.edge_traversals,
    )
    
    return result


__all__ = [
    "DiffusionResult",
    "HotNode",
    "SubgraphEdge",
    "build_adjacency_list",
    "diffuse_heat",
    "fetch_hot_nodes",
    "fetch_subgraph",
    "propagate_heat_bfs",
]
```

- [ ] **Step 3.4: Commit**

```bash
git add src/context_service/signals/diffusion.py
git commit -m "feat(diffusion): add database queries and main diffuse_heat function"
```

---

## Task 4: Dagster Asset - heat_diffusion

**Files:**
- Create: `src/context_service/pipelines/assets/heat_diffusion.py`
- Modify: `src/context_service/pipelines/assets/__init__.py`

- [ ] **Step 4.1: Create heat_diffusion asset**

```python
# src/context_service/pipelines/assets/heat_diffusion.py
"""Dagster asset: propagate heat from hot nodes to neighbors."""

import asyncio
import concurrent.futures
import time
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext
from opentelemetry import trace

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource

tracer = trace.get_tracer(__name__)


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


@dg.asset(
    name="heat_diffusion",
    deps=["heat"],
    partitions_def=silo_partitions,
    description="Propagate heat from hot nodes to neighbors via BFS",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "heat_diffusion"},
)
def heat_diffusion_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Propagate heat from hot nodes to neighbors."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.config.diffusion import load_diffusion_config
        from context_service.signals.diffusion import (
            diffuse_heat,
            get_materialization_distribution,
        )

        config = load_diffusion_config()
        
        if not config.enabled:
            context.log.info(f"silo={silo_id} heat_diffusion disabled, skipping")
            return {"skipped": True}

        store = await memgraph.store()

        with tracer.start_as_current_span("heat_diffusion") as span:
            span.set_attribute("silo_id", silo_id)
            
            result = await diffuse_heat(store, silo_id, config)
            
            span.set_attribute("hot_nodes", result.hot_nodes)
            span.set_attribute("nodes_updated", result.nodes_updated)

        distribution = await get_materialization_distribution(store, silo_id)

        return {
            "silo_id": silo_id,
            "hot_nodes": result.hot_nodes,
            "nodes_updated": result.nodes_updated,
            "edge_traversals": result.edge_traversals,
            "distribution": distribution,
        }

    output = _run_async(_run())
    duration_s = time.monotonic() - t0

    if output.get("skipped"):
        return dg.Output(value=output)

    context.log.info(
        f"silo={silo_id} hot_nodes={output['hot_nodes']} "
        f"nodes_updated={output['nodes_updated']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**output, "duration_s": duration_s},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "hot_nodes": dg.MetadataValue.int(output["hot_nodes"]),
            "nodes_updated": dg.MetadataValue.int(output["nodes_updated"]),
            "edge_traversals": dg.MetadataValue.json(output["edge_traversals"]),
            "distribution": dg.MetadataValue.json(output["distribution"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["heat_diffusion_asset"]
```

- [ ] **Step 4.2: Export from __init__.py**

Add to `src/context_service/pipelines/assets/__init__.py`:

```python
from context_service.pipelines.assets.heat_diffusion import heat_diffusion_asset
```

And add `"heat_diffusion_asset"` to the `__all__` list.

- [ ] **Step 4.3: Commit**

```bash
git add src/context_service/pipelines/assets/heat_diffusion.py src/context_service/pipelines/assets/__init__.py
git commit -m "feat(diffusion): add heat_diffusion Dagster asset"
```

---

## Task 5: Dagster Asset - prewarm_sweep

**Files:**
- Create: `src/context_service/pipelines/assets/prewarm_sweep.py`
- Modify: `src/context_service/pipelines/assets/__init__.py`

- [ ] **Step 5.1: Create prewarm_sweep asset**

```python
# src/context_service/pipelines/assets/prewarm_sweep.py
"""Dagster asset: trigger background work for warming nodes."""

import asyncio
import concurrent.futures
import time
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


FETCH_WARMING_NODES_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.materialization_level IN ['FULL', 'WARM']
  AND (n.prewarmed_at IS NULL OR n.prewarmed_at < $cutoff)
RETURN n.id AS id, n.effective_heat AS effective_heat,
       n.materialization_level AS level
ORDER BY n.effective_heat DESC
LIMIT 100
"""

MARK_PREWARMED_QUERY = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
SET n.prewarmed_at = $now
"""


@dg.asset(
    name="prewarm_sweep",
    deps=["heat_diffusion"],
    partitions_def=silo_partitions,
    description="Trigger background work for nodes transitioning to WARM/FULL",
    retry_policy=dg.RetryPolicy(max_retries=2, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
    tags={"dagster/concurrency_key": "prewarm_sweep"},
)
def prewarm_sweep_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Find warming nodes and prioritize background work."""
    silo_id: str = context.partition_key
    t0 = time.monotonic()

    async def _run() -> dict[str, Any]:
        from context_service.config.diffusion import load_prewarm_config

        config = load_prewarm_config()
        
        if not config.enabled:
            context.log.info(f"silo={silo_id} prewarm disabled, skipping")
            return {"skipped": True}

        store = await memgraph.store()
        now = datetime.now(UTC)
        cutoff = (now.replace(hour=now.hour - 1)).isoformat()

        rows = await store.execute_query(
            FETCH_WARMING_NODES_QUERY,
            {"silo_id": silo_id, "cutoff": cutoff},
        )

        if not rows:
            return {"warming_nodes": 0}

        node_ids = [row["id"] for row in rows]
        
        await store.execute_write(
            MARK_PREWARMED_QUERY,
            {"silo_id": silo_id, "node_ids": node_ids, "now": now.isoformat()},
        )

        return {
            "warming_nodes": len(rows),
            "full_count": sum(1 for r in rows if r["level"] == "FULL"),
            "warm_count": sum(1 for r in rows if r["level"] == "WARM"),
        }

    output = _run_async(_run())
    duration_s = time.monotonic() - t0

    if output.get("skipped"):
        return dg.Output(value=output)

    context.log.info(
        f"silo={silo_id} warming_nodes={output['warming_nodes']} duration={duration_s:.2f}s"
    )

    return dg.Output(
        value={**output, "silo_id": silo_id, "duration_s": duration_s},
        metadata={
            "silo_id": dg.MetadataValue.text(silo_id),
            "warming_nodes": dg.MetadataValue.int(output["warming_nodes"]),
            "duration_s": dg.MetadataValue.float(duration_s),
        },
    )


__all__ = ["prewarm_sweep_asset"]
```

- [ ] **Step 5.2: Export from __init__.py**

Add to `src/context_service/pipelines/assets/__init__.py`:

```python
from context_service.pipelines.assets.prewarm_sweep import prewarm_sweep_asset
```

And add `"prewarm_sweep_asset"` to the `__all__` list.

- [ ] **Step 5.3: Commit**

```bash
git add src/context_service/pipelines/assets/prewarm_sweep.py src/context_service/pipelines/assets/__init__.py
git commit -m "feat(diffusion): add prewarm_sweep Dagster asset"
```

---

## Task 6: Retrieval Integration

**Files:**
- Modify: `src/context_service/services/context.py`

- [ ] **Step 6.1: Find current heat usage in context.py**

Run: `grep -n "heat_score" src/context_service/services/context.py`

Locate where `heat_score` is used in ranking.

- [ ] **Step 6.2: Update to use effective_heat**

Find the line that looks like:
```python
heat = node.heat_score or 0.5
```

Replace with:
```python
heat = getattr(node, 'effective_heat', None) or getattr(node, 'heat_score', None) or 0.5
```

Or if accessing from dict:
```python
heat = node.get("effective_heat") or node.get("heat_score") or 0.5
```

- [ ] **Step 6.3: Commit**

```bash
git add src/context_service/services/context.py
git commit -m "feat(diffusion): use effective_heat in retrieval ranking"
```

---

## Task 7: Integration Tests

**Files:**
- Create: `tests/pipelines/test_heat_diffusion.py`

- [ ] **Step 7.1: Write integration test**

```python
# tests/pipelines/test_heat_diffusion.py
"""Integration tests for heat diffusion pipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.signals.diffusion import (
    DiffusionResult,
    HotNode,
    SubgraphEdge,
    build_adjacency_list,
    propagate_heat_bfs,
)
from context_service.config.diffusion import DiffusionConfig


class TestHeatDiffusionIntegration:
    """Test heat diffusion with realistic graph structures."""

    def test_linear_chain_propagation(self):
        """Heat decays along a linear chain: A -> B -> C -> D"""
        config = DiffusionConfig(hop_decay=0.7, max_depth=3)
        
        edges = [
            SubgraphEdge("A", "B", "SUPPORTS", 1.0),
            SubgraphEdge("B", "C", "SUPPORTS", 1.0),
            SubgraphEdge("C", "D", "SUPPORTS", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="A", heat_score=1.0)]
        
        result = propagate_heat_bfs(hot_nodes, adjacency, config)
        
        assert result.propagation_map["B"] > result.propagation_map["C"]
        assert result.propagation_map["C"] > result.propagation_map["D"]

    def test_multiple_sources_max_heat(self):
        """Node reached by multiple hot sources gets max heat."""
        config = DiffusionConfig(hop_decay=0.7, max_depth=2)
        
        edges = [
            SubgraphEdge("hot1", "target", "SUPPORTS", 1.0),
            SubgraphEdge("hot2", "target", "SUPPORTS", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        
        hot_nodes = [
            HotNode(id="hot1", heat_score=1.0),
            HotNode(id="hot2", heat_score=0.5),
        ]
        
        result = propagate_heat_bfs(hot_nodes, adjacency, config)
        
        expected_from_hot1 = 1.0 * 0.7 * 0.9 * 1.0
        assert result.propagation_map["target"] == pytest.approx(expected_from_hot1, rel=0.01)

    def test_edge_type_weights(self):
        """Different edge types propagate different amounts of heat."""
        config = DiffusionConfig(hop_decay=1.0, max_depth=1)
        
        edges = [
            SubgraphEdge("hot", "contradicts_target", "CONTRADICTS", 1.0),
            SubgraphEdge("hot", "related_target", "RELATED_TO", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="hot", heat_score=1.0)]
        
        result = propagate_heat_bfs(hot_nodes, adjacency, config)
        
        assert result.propagation_map["contradicts_target"] == pytest.approx(0.95, rel=0.01)
        assert result.propagation_map["related_target"] == pytest.approx(0.40, rel=0.01)

    def test_edge_heat_affects_propagation(self):
        """Edges with low heat propagate less."""
        config = DiffusionConfig(hop_decay=1.0, max_depth=1)
        
        edges = [
            SubgraphEdge("hot", "hot_edge", "SUPPORTS", 1.0),
            SubgraphEdge("hot", "cold_edge", "SUPPORTS", 0.1),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="hot", heat_score=1.0)]
        
        result = propagate_heat_bfs(hot_nodes, adjacency, config)
        
        assert result.propagation_map["hot_edge"] > result.propagation_map["cold_edge"] * 5

    def test_min_threshold_stops_propagation(self):
        """Propagation stops when heat falls below threshold."""
        config = DiffusionConfig(hop_decay=0.1, min_threshold=0.05, max_depth=5)
        
        edges = [
            SubgraphEdge("A", "B", "RELATED_TO", 1.0),
            SubgraphEdge("B", "C", "RELATED_TO", 1.0),
            SubgraphEdge("C", "D", "RELATED_TO", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="A", heat_score=1.0)]
        
        result = propagate_heat_bfs(hot_nodes, adjacency, config)
        
        assert "B" in result.propagation_map
        assert "D" not in result.propagation_map
```

- [ ] **Step 7.2: Run integration tests**

Run: `uv run pytest tests/pipelines/test_heat_diffusion.py -v`
Expected: PASS

- [ ] **Step 7.3: Commit**

```bash
git add tests/pipelines/test_heat_diffusion.py
git commit -m "test(diffusion): add integration tests for heat propagation"
```

---

## Task 8: Final Verification

- [ ] **Step 8.1: Run full test suite**

Run: `uv run pytest tests/ -v --ignore=tests/integration`
Expected: All tests pass

- [ ] **Step 8.2: Run type checking**

Run: `uv run mypy src/context_service/signals/diffusion.py src/context_service/config/diffusion.py src/context_service/pipelines/assets/heat_diffusion.py src/context_service/pipelines/assets/prewarm_sweep.py`
Expected: No errors

- [ ] **Step 8.3: Run linting**

Run: `uv run ruff check src/context_service/signals/diffusion.py src/context_service/config/diffusion.py src/context_service/pipelines/assets/heat_diffusion.py src/context_service/pipelines/assets/prewarm_sweep.py`
Expected: No errors

- [ ] **Step 8.4: Final commit**

```bash
git add -A
git commit -m "feat(diffusion): complete heat diffusion implementation

- Config: YAML-based with env overrides
- Algorithm: Python BFS with batched subgraph fetch
- Assets: heat_diffusion and prewarm_sweep Dagster assets
- Retrieval: Use effective_heat in ranking
- Tests: Unit and integration coverage

Closes: heat-diffusion-v1.5"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Configuration | config/diffusion.yaml, config/diffusion.py |
| 2 | BFS Algorithm | signals/diffusion.py |
| 3 | Database Queries | signals/diffusion.py |
| 4 | heat_diffusion Asset | pipelines/assets/heat_diffusion.py |
| 5 | prewarm_sweep Asset | pipelines/assets/prewarm_sweep.py |
| 6 | Retrieval Integration | services/context.py |
| 7 | Integration Tests | tests/pipelines/test_heat_diffusion.py |
| 8 | Final Verification | All files |

**Estimated time:** 2-3 hours for experienced developer
