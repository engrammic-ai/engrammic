# Phase 6: Query and Recall Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement RECALL query transaction with epistemic-aware scoring and lazy synthesis trigger. Also fix WOULD_CREATE_CYCLE query syntax bug from Phase 1.

**Architecture:** Add `sage/recall.py` with query logic that combines vector search, layer-specific scoring, graph traversal, and lazy synthesis. The recall path is read-only with an optional sync synthesis side-effect.

**Tech Stack:** Python 3.12, Memgraph (Cypher), Qdrant (vector search), AsyncMock for testing, pytest

**Spec Reference:** `context/specs/brain-transactions-pseudocode.md` lines 1536-1735

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/sage/recall.py` | New file: RECALL transaction, COMPUTE_RECALL_SCORE helper, TRAVERSE_GRAPH helper |
| `src/context_service/sage/transactions.py` | Add WOULD_CREATE_CYCLE helper function (fix syntax bug) |
| `src/context_service/db/queries.py` | Add TRAVERSE_NEIGHBORS, CHECK_CYCLE_PATH queries |
| `tests/sage/test_recall.py` | New test file for RECALL, COMPUTE_RECALL_SCORE tests |
| `tests/sage/test_transactions.py` | Add tests for WOULD_CREATE_CYCLE |

---

## Task 1: Add Result Dataclasses and Options

**Files:**
- Create: `src/context_service/sage/recall.py`

- [ ] **Step 1: Create recall.py with imports and dataclasses**

```python
"""Sage recall: Query transaction with epistemic-aware scoring.

Implements RECALL, COMPUTE_RECALL_SCORE, TRAVERSE_GRAPH per brain-transactions-pseudocode.md.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from context_service.sage.transactions import (
    ClusterState,
    NodeState,
    SynthesisState,
)

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore, VectorStore

logger = structlog.get_logger(__name__)

# Scoring constants
MEMORY_DECAY_SIGMA = 90  # days
MAX_GRAPH_DEPTH = 3
MAX_NEIGHBORS_PER_NODE = 20
LAZY_SYNTHESIS_TIMEOUT_MS = 2000


class Layer(StrEnum):
    """Cognitive layers per CITE v2."""

    MEMORY = "MEMORY"
    KNOWLEDGE = "KNOWLEDGE"
    WISDOM = "WISDOM"
    INTELLIGENCE = "INTELLIGENCE"


@dataclass
class RecallOptions:
    """Options for RECALL query."""

    top_k: int = 10
    layers: list[Layer] | None = None
    include_superseded: bool = False
    as_of: datetime | None = None
    include_synthesis: bool = True
    min_confidence: float = 0.0
    depth: int = 0


@dataclass
class RelatedNode:
    """A node related to a recall result via graph traversal."""

    node_id: str
    edge_type: str
    direction: str  # 'outgoing' or 'incoming'
    depth: int
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallResultItem:
    """A single result from RECALL."""

    node_id: str
    content: str
    layer: str
    score: float
    confidence: float
    created_at: datetime
    properties: dict[str, Any] = field(default_factory=dict)
    related: list[RelatedNode] = field(default_factory=list)
    synthesized: bool = False


@dataclass
class RecallResult:
    """Result of RECALL query."""

    results: list[RecallResultItem]
    total_candidates: int
    synthesis_pending: list[str]
    query_time_ms: float
```

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from context_service.sage.recall import RecallOptions, RecallResult, RecallResultItem; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/recall.py
git commit -m "feat(sage): add recall dataclasses and options for Phase 6"
```

---

## Task 2: Add Cypher Queries

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add TRAVERSE_NEIGHBORS query**

```python
TRAVERSE_NEIGHBORS = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[e]-(neighbor)
WHERE neighbor.properties.state = 'ACTIVE'
  AND NOT neighbor.id IN $visited
RETURN neighbor.id AS id,
       type(e) AS edge_type,
       CASE WHEN startNode(e) = n THEN 'outgoing' ELSE 'incoming' END AS direction,
       neighbor.properties AS properties
LIMIT $limit
"""
```

- [ ] **Step 2: Add CHECK_CYCLE_PATH query**

```python
CHECK_CYCLE_PATH = """
MATCH path = (source {id: $source_id, silo_id: $silo_id})-[:SUPERSEDES*1..10]->(target {id: $target_id, silo_id: $silo_id})
RETURN count(path) > 0 AS would_cycle
"""
```

- [ ] **Step 3: Add GET_NODE_FOR_RECALL query**

```python
GET_NODE_FOR_RECALL = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.id AS id,
       n.properties.content AS content,
       n.properties.layer AS layer,
       n.properties.state AS state,
       n.properties.confidence AS confidence,
       n.properties.corroboration_count AS corroboration_count,
       n.properties.synthesis_state AS synthesis_state,
       n.properties.created_at AS created_at,
       n.properties.valid_to AS valid_to,
       n.properties AS properties
"""
```

- [ ] **Step 4: Add GET_CLUSTERS_FOR_NODES query**

```python
GET_CLUSTERS_FOR_NODES = """
MATCH (n {silo_id: $silo_id})-[:MEMBER_OF]->(cluster:Cluster)
WHERE n.id IN $node_ids
RETURN cluster.id AS cluster_id,
       cluster.properties.state AS state,
       cluster.properties.current_belief_id AS current_belief_id
"""
```

- [ ] **Step 5: Verify queries are valid Python**

Run: `uv run python -c "from context_service.db import queries; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Cypher queries for Phase 6 recall and cycle detection"
```

---

## Task 3: Implement COMPUTE_RECALL_SCORE Helper

**Files:**
- Modify: `src/context_service/sage/recall.py`

- [ ] **Step 1: Add gaussian_decay helper**

```python
def gaussian_decay(age_days: float, sigma: float = MEMORY_DECAY_SIGMA) -> float:
    """Apply Gaussian decay based on age.

    Returns value in [0, 1], with 1 at age=0 and decaying towards 0.
    """
    return math.exp(-(age_days**2) / (2 * sigma**2))


def days_since(dt: datetime) -> float:
    """Calculate days since a datetime."""
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    return delta.total_seconds() / 86400
```

- [ ] **Step 2: Add compute_recall_score function**

```python
def compute_recall_score(
    node: dict[str, Any],
    similarity: float,
    heat: float = 0.0,
) -> float:
    """Compute retrieval score with layer-specific semantics.

    Per brain-transactions-pseudocode.md COMPUTE_RECALL_SCORE:
    - Memory: Apply freshness decay
    - Knowledge: Weight by confidence and corroboration
    - Wisdom: Weight by evidence strength, penalize stale
    - Intelligence: No decay (session-scoped)
    """
    layer = node.get("layer", "MEMORY")
    confidence = node.get("confidence", 0.5)
    created_at = node.get("created_at")

    # Parse created_at if string
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    elif created_at is None:
        created_at = datetime.now(UTC)

    # Layer-specific scoring
    if layer == Layer.MEMORY.value:
        # Apply freshness decay
        age = days_since(created_at)
        freshness = gaussian_decay(age)
        layer_score = similarity * freshness

    elif layer == Layer.KNOWLEDGE.value:
        # Weight by confidence and corroboration
        corroboration_count = node.get("corroboration_count", 0)
        corroboration_boost = math.log(1 + corroboration_count) / math.log(10) if corroboration_count > 0 else 0
        layer_score = similarity * confidence * (1 + corroboration_boost * 0.2)

    elif layer == Layer.WISDOM.value:
        # Weight by confidence, penalize stale
        synthesis_state = node.get("synthesis_state", SynthesisState.FRESH.value)
        staleness_penalty = 0.5 if synthesis_state == SynthesisState.STALE.value else 1.0
        layer_score = similarity * confidence * staleness_penalty

    elif layer == Layer.INTELLIGENCE.value:
        # Session-scoped, no decay
        layer_score = similarity

    else:
        # Default: just similarity
        layer_score = similarity

    # Apply heat boost (max 10% boost)
    heat_boost = 1 + (heat * 0.1)
    final_score = layer_score * heat_boost

    return max(0.0, min(1.0, final_score))
```

- [ ] **Step 3: Verify imports work**

Run: `uv run python -c "from context_service.sage.recall import compute_recall_score; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/recall.py
git commit -m "feat(sage): implement COMPUTE_RECALL_SCORE helper"
```

---

## Task 4: Implement TRAVERSE_GRAPH Helper

**Files:**
- Modify: `src/context_service/sage/recall.py`

- [ ] **Step 1: Add traverse_graph function**

```python
async def traverse_graph(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    max_depth: int,
    current_depth: int = 1,
    visited: set[str] | None = None,
) -> list[RelatedNode]:
    """Traverse graph to find related nodes up to max_depth.

    Per brain-transactions-pseudocode.md TRAVERSE_GRAPH.
    """
    from context_service.db import queries as q

    if visited is None:
        visited = set()

    if current_depth > max_depth:
        return []

    visited.add(node_id)

    # Get immediate neighbors
    neighbors = await store.execute_query(
        q.TRAVERSE_NEIGHBORS,
        {
            "node_id": node_id,
            "silo_id": silo_id,
            "visited": list(visited),
            "limit": MAX_NEIGHBORS_PER_NODE,
        },
    )

    results: list[RelatedNode] = []
    for neighbor in neighbors:
        neighbor_id = neighbor.get("id")
        if neighbor_id is None:
            continue

        results.append(
            RelatedNode(
                node_id=neighbor_id,
                edge_type=neighbor.get("edge_type", "RELATED_TO"),
                direction=neighbor.get("direction", "outgoing"),
                depth=current_depth,
                properties=neighbor.get("properties", {}),
            )
        )

        # Recurse
        if current_depth < max_depth:
            child_results = await traverse_graph(
                store=store,
                node_id=neighbor_id,
                silo_id=silo_id,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                visited=visited,
            )
            results.extend(child_results)

    return results
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/sage/recall.py
git commit -m "feat(sage): implement TRAVERSE_GRAPH helper"
```

---

## Task 5: Implement RECALL Transaction

**Files:**
- Modify: `src/context_service/sage/recall.py`

- [ ] **Step 1: Add recall function signature and validation**

```python
async def recall(
    store: HyperGraphStore,
    vector_store: VectorStore,
    embedding_service: EmbeddingService,
    query: str,
    silo_id: str,
    options: RecallOptions | None = None,
) -> RecallResult:
    """RECALL: Query transaction with epistemic-aware retrieval.

    Per brain-transactions-pseudocode.md RECALL:
    1. Vector search with over-fetch
    2. Apply filters (state, temporal, layer, confidence)
    3. Score by layer semantics
    4. Graph traversal (if depth > 0)
    5. Lazy synthesis (if enabled)
    """
    from context_service.db import queries as q
    from context_service.sage.transactions import tx4_synthesize

    start_time = datetime.now(UTC)

    if options is None:
        options = RecallOptions()

    # Validation
    if not silo_id:
        raise ValueError("silo_id is required")
    if not query or not query.strip():
        raise ValueError("query is required")

    # 1. Vector search
    query_embedding = await embedding_service.embed_text(query)

    # Over-fetch for filtering
    over_fetch_k = options.top_k * 3
    candidates = await vector_store.search(
        collection=silo_id,
        vector=query_embedding,
        top_k=over_fetch_k,
    )
```

- [ ] **Step 2: Add filtering logic**

```python
    # 2. Apply filters
    filtered: list[tuple[dict[str, Any], float]] = []

    for candidate in candidates:
        node_id = candidate.get("id")
        similarity = candidate.get("score", 0.0)

        # Fetch full node
        node_results = await store.execute_query(
            q.GET_NODE_FOR_RECALL,
            {"node_id": node_id, "silo_id": silo_id},
        )
        if not node_results:
            continue

        node = node_results[0]

        # State filter
        state = node.get("state")
        if state in (NodeState.TOMBSTONED.value, NodeState.DELETED.value):
            continue

        if state == NodeState.SUPERSEDED.value and not options.include_superseded:
            continue

        # Temporal filter (as_of)
        if options.as_of is not None:
            created_at = node.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created_at > options.as_of:
                    continue

            valid_to = node.get("valid_to")
            if valid_to:
                if isinstance(valid_to, str):
                    valid_to = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
                if valid_to < options.as_of:
                    continue

        # Layer filter
        if options.layers is not None:
            node_layer = node.get("layer")
            if node_layer not in [l.value for l in options.layers]:
                continue

        # Confidence filter
        confidence = node.get("confidence", 0.0)
        if confidence < options.min_confidence:
            continue

        filtered.append((node, similarity))
```

- [ ] **Step 3: Add scoring and result building**

```python
    # 3. Score by layer semantics
    scored: list[tuple[dict[str, Any], float, float]] = []
    for node, similarity in filtered:
        # TODO: Get heat from Redis when reactions are implemented
        heat = 0.0
        score = compute_recall_score(node, similarity, heat)
        scored.append((node, score, similarity))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top_k
    top_results = scored[: options.top_k]

    # 4. Graph traversal (if depth > 0)
    results: list[RecallResultItem] = []
    for node, score, similarity in top_results:
        related: list[RelatedNode] = []
        if options.depth > 0:
            related = await traverse_graph(
                store=store,
                node_id=node.get("id"),
                silo_id=silo_id,
                max_depth=options.depth,
            )

        created_at = node.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif created_at is None:
            created_at = datetime.now(UTC)

        results.append(
            RecallResultItem(
                node_id=node.get("id"),
                content=node.get("content", ""),
                layer=node.get("layer", "MEMORY"),
                score=score,
                confidence=node.get("confidence", 0.0),
                created_at=created_at,
                properties=node.get("properties", {}),
                related=related,
                synthesized=False,
            )
        )
```

- [ ] **Step 4: Add lazy synthesis logic**

```python
    # 5. Lazy synthesis (if enabled)
    synthesis_pending: list[str] = []
    if options.include_synthesis and results:
        node_ids = [r.node_id for r in results]

        # Get clusters for result nodes
        cluster_results = await store.execute_query(
            q.GET_CLUSTERS_FOR_NODES,
            {"silo_id": silo_id, "node_ids": node_ids},
        )

        for cluster in cluster_results:
            cluster_id = cluster.get("cluster_id")
            cluster_state = cluster.get("state")
            current_belief_id = cluster.get("current_belief_id")

            if cluster_state in (ClusterState.READY.value, ClusterState.STALE.value):
                if current_belief_id is None:
                    # Trigger lazy synthesis (sync mode with timeout)
                    try:
                        belief_result, _ = await tx4_synthesize(
                            store=store,
                            cluster_id=cluster_id,
                            silo_id=silo_id,
                            mode="SYNC",
                            llm=None,  # Will use default
                            embedding_service=embedding_service,
                        )
                        if belief_result and belief_result.belief_id:
                            # Add synthesized belief to results
                            results.append(
                                RecallResultItem(
                                    node_id=str(belief_result.belief_id),
                                    content=belief_result.content or "",
                                    layer=Layer.WISDOM.value,
                                    score=1.0,
                                    confidence=belief_result.confidence,
                                    created_at=datetime.now(UTC),
                                    properties={},
                                    related=[],
                                    synthesized=True,
                                )
                            )
                    except Exception as e:
                        logger.warning(
                            "lazy_synthesis_failed",
                            cluster_id=cluster_id,
                            error=str(e),
                        )
                        synthesis_pending.append(cluster_id)

    # 6. Build response
    elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

    return RecallResult(
        results=results,
        total_candidates=len(candidates),
        synthesis_pending=synthesis_pending,
        query_time_ms=elapsed_ms,
    )
```

- [ ] **Step 5: Verify imports work**

Run: `uv run python -c "from context_service.sage.recall import recall; print('OK')"`

- [ ] **Step 6: Commit**

```bash
git add src/context_service/sage/recall.py
git commit -m "feat(sage): implement RECALL transaction with lazy synthesis"
```

---

## Task 6: Fix WOULD_CREATE_CYCLE Query

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add would_create_cycle helper function**

This fixes the Cypher syntax bug noted in Phase 1 review. The pseudocode has an incorrect WHERE clause.

```python
async def would_create_cycle(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    silo_id: str,
    edge_type: str = "SUPERSEDES",
) -> bool:
    """Check if adding edge would create cycle in SUPERSEDES graph.

    Per brain-transactions-pseudocode.md WOULD_CREATE_CYCLE.
    Only checks SUPERSEDES cycles (INV4).
    """
    if edge_type != "SUPERSEDES":
        return False

    from context_service.db import queries as q

    # Check if path exists from target to source
    result = await store.execute_query(
        q.CHECK_CYCLE_PATH,
        {
            "source_id": target_id,  # Start from target
            "target_id": source_id,  # See if we can reach source
            "silo_id": silo_id,
        },
    )

    if result and result[0].get("would_cycle"):
        return True

    return False
```

- [ ] **Step 2: Update tx3_supersede to use the helper**

Find the existing cycle check in tx3_supersede and update to use the new helper.

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py src/context_service/db/queries.py
git commit -m "fix(sage): implement WOULD_CREATE_CYCLE helper with correct Cypher"
```

---

## Task 7: Write Tests

**Files:**
- Create: `tests/sage/test_recall.py`

- [ ] **Step 1: Create test file with imports and fixtures**

```python
"""Tests for Phase 6 recall transaction (RECALL, COMPUTE_RECALL_SCORE)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from context_service.sage.recall import (
    Layer,
    RecallOptions,
    RecallResult,
    RecallResultItem,
    compute_recall_score,
    gaussian_decay,
    recall,
    traverse_graph,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    store.execute_write = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_vector_store() -> AsyncMock:
    """Create a mock VectorStore."""
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    return store


@pytest.fixture
def mock_embedding_service() -> AsyncMock:
    """Create a mock EmbeddingService."""
    service = AsyncMock()
    service.embed_text = AsyncMock(return_value=[0.1] * 768)
    return service


def make_uuid() -> str:
    """Generate a valid UUID string for tests."""
    return str(uuid.uuid4())
```

- [ ] **Step 2: Add tests for gaussian_decay**

```python
class TestGaussianDecay:
    """Tests for gaussian_decay helper."""

    def test_returns_one_at_zero_age(self) -> None:
        """Test that decay is 1 at age 0."""
        assert gaussian_decay(0) == pytest.approx(1.0)

    def test_decreases_with_age(self) -> None:
        """Test that decay decreases with age."""
        assert gaussian_decay(30) > gaussian_decay(60)
        assert gaussian_decay(60) > gaussian_decay(90)

    def test_respects_sigma_parameter(self) -> None:
        """Test that sigma affects decay rate."""
        # Smaller sigma = faster decay
        assert gaussian_decay(30, sigma=30) < gaussian_decay(30, sigma=90)
```

- [ ] **Step 3: Add tests for compute_recall_score**

```python
class TestComputeRecallScore:
    """Tests for COMPUTE_RECALL_SCORE."""

    def test_memory_layer_applies_freshness_decay(self) -> None:
        """Test that memory layer applies freshness decay."""
        now = datetime.now(UTC)
        old_node = {
            "layer": "MEMORY",
            "confidence": 0.8,
            "created_at": (now - timedelta(days=180)).isoformat(),
        }
        new_node = {
            "layer": "MEMORY",
            "confidence": 0.8,
            "created_at": now.isoformat(),
        }

        old_score = compute_recall_score(old_node, similarity=0.9)
        new_score = compute_recall_score(new_node, similarity=0.9)

        assert new_score > old_score

    def test_knowledge_layer_boosts_corroboration(self) -> None:
        """Test that knowledge layer boosts corroborated claims."""
        base_node = {
            "layer": "KNOWLEDGE",
            "confidence": 0.8,
            "corroboration_count": 0,
            "created_at": datetime.now(UTC).isoformat(),
        }
        corroborated_node = {
            "layer": "KNOWLEDGE",
            "confidence": 0.8,
            "corroboration_count": 5,
            "created_at": datetime.now(UTC).isoformat(),
        }

        base_score = compute_recall_score(base_node, similarity=0.9)
        corroborated_score = compute_recall_score(corroborated_node, similarity=0.9)

        assert corroborated_score > base_score

    def test_wisdom_layer_penalizes_stale(self) -> None:
        """Test that wisdom layer penalizes stale beliefs."""
        fresh_node = {
            "layer": "WISDOM",
            "confidence": 0.8,
            "synthesis_state": "FRESH",
            "created_at": datetime.now(UTC).isoformat(),
        }
        stale_node = {
            "layer": "WISDOM",
            "confidence": 0.8,
            "synthesis_state": "STALE",
            "created_at": datetime.now(UTC).isoformat(),
        }

        fresh_score = compute_recall_score(fresh_node, similarity=0.9)
        stale_score = compute_recall_score(stale_node, similarity=0.9)

        assert fresh_score > stale_score

    def test_heat_boost_applied(self) -> None:
        """Test that heat provides a score boost."""
        node = {
            "layer": "MEMORY",
            "confidence": 0.8,
            "created_at": datetime.now(UTC).isoformat(),
        }

        cold_score = compute_recall_score(node, similarity=0.9, heat=0.0)
        hot_score = compute_recall_score(node, similarity=0.9, heat=1.0)

        assert hot_score > cold_score

    def test_score_clamped_to_zero_one(self) -> None:
        """Test that score is clamped to [0, 1]."""
        node = {
            "layer": "KNOWLEDGE",
            "confidence": 1.0,
            "corroboration_count": 100,
            "created_at": datetime.now(UTC).isoformat(),
        }

        score = compute_recall_score(node, similarity=1.0, heat=1.0)
        assert 0 <= score <= 1
```

- [ ] **Step 4: Add tests for recall transaction**

```python
class TestRecall:
    """Tests for RECALL transaction."""

    @pytest.mark.asyncio
    async def test_returns_results_from_vector_search(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall returns results from vector search."""
        node_id = make_uuid()

        mock_vector_store.search = AsyncMock(
            return_value=[{"id": node_id, "score": 0.9}]
        )
        mock_store.execute_query = AsyncMock(
            side_effect=[
                # GET_NODE_FOR_RECALL
                [{
                    "id": node_id,
                    "content": "Test content",
                    "layer": "MEMORY",
                    "state": "ACTIVE",
                    "confidence": 0.8,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                # GET_CLUSTERS_FOR_NODES
                [],
            ]
        )

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="test-silo",
        )

        assert isinstance(result, RecallResult)
        assert len(result.results) == 1
        assert result.results[0].node_id == node_id

    @pytest.mark.asyncio
    async def test_filters_tombstoned_nodes(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall filters out tombstoned nodes."""
        node_id = make_uuid()

        mock_vector_store.search = AsyncMock(
            return_value=[{"id": node_id, "score": 0.9}]
        )
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [{
                    "id": node_id,
                    "content": "Test content",
                    "layer": "MEMORY",
                    "state": "TOMBSTONED",
                    "confidence": 0.8,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                [],
            ]
        )

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="test-silo",
        )

        assert len(result.results) == 0

    @pytest.mark.asyncio
    async def test_filters_by_layer(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall filters by layer option."""
        memory_id = make_uuid()
        knowledge_id = make_uuid()

        mock_vector_store.search = AsyncMock(
            return_value=[
                {"id": memory_id, "score": 0.9},
                {"id": knowledge_id, "score": 0.8},
            ]
        )
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [{
                    "id": memory_id,
                    "content": "Memory",
                    "layer": "MEMORY",
                    "state": "ACTIVE",
                    "confidence": 0.8,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                [{
                    "id": knowledge_id,
                    "content": "Knowledge",
                    "layer": "KNOWLEDGE",
                    "state": "ACTIVE",
                    "confidence": 0.8,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                [],
            ]
        )

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="test-silo",
            options=RecallOptions(layers=[Layer.KNOWLEDGE]),
        )

        assert len(result.results) == 1
        assert result.results[0].layer == "KNOWLEDGE"

    @pytest.mark.asyncio
    async def test_respects_min_confidence(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall filters by min_confidence."""
        low_id = make_uuid()
        high_id = make_uuid()

        mock_vector_store.search = AsyncMock(
            return_value=[
                {"id": low_id, "score": 0.9},
                {"id": high_id, "score": 0.8},
            ]
        )
        mock_store.execute_query = AsyncMock(
            side_effect=[
                [{
                    "id": low_id,
                    "content": "Low confidence",
                    "layer": "KNOWLEDGE",
                    "state": "ACTIVE",
                    "confidence": 0.3,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                [{
                    "id": high_id,
                    "content": "High confidence",
                    "layer": "KNOWLEDGE",
                    "state": "ACTIVE",
                    "confidence": 0.9,
                    "created_at": datetime.now(UTC).isoformat(),
                    "properties": {},
                }],
                [],
            ]
        )

        result = await recall(
            store=mock_store,
            vector_store=mock_vector_store,
            embedding_service=mock_embedding_service,
            query="test query",
            silo_id="test-silo",
            options=RecallOptions(min_confidence=0.5),
        )

        assert len(result.results) == 1
        assert result.results[0].confidence >= 0.5

    @pytest.mark.asyncio
    async def test_raises_on_empty_query(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall raises on empty query."""
        with pytest.raises(ValueError, match="query is required"):
            await recall(
                store=mock_store,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding_service,
                query="",
                silo_id="test-silo",
            )

    @pytest.mark.asyncio
    async def test_raises_on_missing_silo(
        self,
        mock_store: AsyncMock,
        mock_vector_store: AsyncMock,
        mock_embedding_service: AsyncMock,
    ) -> None:
        """Test that recall raises on missing silo_id."""
        with pytest.raises(ValueError, match="silo_id is required"):
            await recall(
                store=mock_store,
                vector_store=mock_vector_store,
                embedding_service=mock_embedding_service,
                query="test",
                silo_id="",
            )
```

- [ ] **Step 5: Add tests for traverse_graph**

```python
class TestTraverseGraph:
    """Tests for TRAVERSE_GRAPH helper."""

    @pytest.mark.asyncio
    async def test_returns_immediate_neighbors(self, mock_store: AsyncMock) -> None:
        """Test that traverse_graph returns immediate neighbors."""
        node_id = make_uuid()
        neighbor_id = make_uuid()

        mock_store.execute_query = AsyncMock(
            return_value=[{
                "id": neighbor_id,
                "edge_type": "RELATED_TO",
                "direction": "outgoing",
                "properties": {"content": "Neighbor"},
            }]
        )

        results = await traverse_graph(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            max_depth=1,
        )

        assert len(results) == 1
        assert results[0].node_id == neighbor_id
        assert results[0].depth == 1

    @pytest.mark.asyncio
    async def test_respects_max_depth(self, mock_store: AsyncMock) -> None:
        """Test that traverse_graph respects max_depth."""
        node_id = make_uuid()

        # Return empty so no recursion
        mock_store.execute_query = AsyncMock(return_value=[])

        results = await traverse_graph(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            max_depth=0,  # No traversal
        )

        assert len(results) == 0
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_recall.py -v`
Expected: Tests fail with ImportError initially

- [ ] **Step 7: Commit failing tests**

```bash
git add tests/sage/test_recall.py
git commit -m "test(sage): add failing tests for Phase 6 RECALL transaction"
```

---

## Task 8: Run Full Test Suite and Lint

- [ ] **Step 1: Run all Phase 6 tests**

Run: `uv run pytest tests/sage/test_recall.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing sage tests**

Run: `uv run pytest tests/sage/ -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 3: Run linter and type checker**

Run: `uv run ruff check src/context_service/sage/`
Run: `uv run mypy src/context_service/sage/recall.py`
Expected: No errors

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "fix(sage): address lint issues in Phase 6 recall"
```

---

## Task 9: Update Module Exports

**Files:**
- Modify: `src/context_service/sage/__init__.py`

- [ ] **Step 1: Add new exports**

Add to imports and __all__:
- RecallOptions
- RecallResult
- RecallResultItem
- RelatedNode
- Layer
- recall
- compute_recall_score
- traverse_graph
- would_create_cycle

- [ ] **Step 2: Verify imports work**

Run: `uv run python -c "from context_service.sage import recall, RecallOptions, RecallResult; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/__init__.py
git commit -m "feat(sage): export Phase 6 recall from module"
```

---

## Task 10: Update Brain Architecture Plan

**Files:**
- Modify: `context/plans/2026-06-01-brain-architecture.md`

- [ ] **Step 1: Mark Phase 6 tasks complete**

Update checkboxes for:
- [x] RECALL query
- [x] COMPUTE_RECALL_SCORE helper
- [x] Fix WOULD_CREATE_CYCLE query syntax bug

- [ ] **Step 2: Update status to "Phase 6 complete, Phase 7 next"**

- [ ] **Step 3: Commit**

```bash
git add context/plans/2026-06-01-brain-architecture.md
git commit -m "docs: mark Phase 6 tasks complete in brain architecture plan"
```

---

## Summary

This plan implements 3 items across 10 tasks:

| Item | Tests | Implementation |
|------|-------|----------------|
| RECALL query | 7 tests | Task 5 |
| COMPUTE_RECALL_SCORE | 5 tests | Task 3 |
| TRAVERSE_GRAPH | 2 tests | Task 4 |
| WOULD_CREATE_CYCLE fix | 1 test (in transactions) | Task 6 |

Total: ~15 new tests, ~300 lines of transaction code, ~30 lines of queries.

**Dependencies:**
- Task 2 (queries) must complete before Tasks 3-6
- Tasks 3 and 4 can run in parallel
- Task 5 depends on Tasks 3 and 4
- Task 7 (tests) can be written in parallel with implementation

**Performance targets (from CLAUDE.md):**
- recall (cached): < 20ms
- recall (search): < 250ms
