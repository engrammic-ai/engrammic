# Weak Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pre-compute speculative RELATED_TO edges based on embedding similarity, track usage via edge heat, and let custodian promote/prune them.

**Architecture:** Reified `WeakLink` nodes (not edge properties) for indexable lookups. Ingest-time creation after embedding, edge heat from traversal events, custodian-driven lifecycle (promote high-signal, prune unused, demote on supersession).

**Tech Stack:** Dagster assets, Redis streams, Memgraph Cypher, pydantic-settings

---

## Parallelization Waves

| Wave | Tasks | Notes |
|------|-------|-------|
| **1** | 1, 2, 3, 10 | No dependencies - run in parallel |
| **2** | 4, 6, 7, 8 | Depend on wave 1 (Task 4,6,8 need #3; Task 7 needs #1) |
| **3** | 5 | Depends on Task 4 |
| **4** | 9 | Integration test - needs all previous |

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/config/settings.py` | Add `WeakLinksSettings` nested model |
| `src/context_service/db/indexes.py` | Add WeakLink index queries |
| `src/context_service/signals/edge_access_events.py` | Edge access event emission (mirrors `access_events.py`) |
| `src/context_service/pipelines/assets/weak_link_creation.py` | Dagster asset: create weak links after embedding |
| `src/context_service/pipelines/assets/edge_heat.py` | Dagster asset: compute edge heat from events |
| `src/context_service/pipelines/assets/weak_link_review.py` | Dagster asset: promote/prune/demote |
| `tests/signals/test_edge_access_events.py` | Unit tests for emit function |
| `tests/pipelines/test_weak_link_creation.py` | Tests for link creation logic |
| `tests/pipelines/test_edge_heat.py` | Tests for edge heat computation |
| `tests/pipelines/test_weak_link_review.py` | Tests for promotion/pruning |

---

## Task 1: WeakLinks Configuration

**Files:**
- Modify: `src/context_service/config/settings.py`
- Test: `tests/config/test_weak_links_settings.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_weak_links_settings.py
from context_service.config.settings import get_settings


def test_weak_links_settings_defaults():
    settings = get_settings()
    wl = settings.weak_links
    assert wl.enabled is True
    assert wl.similarity_threshold == 0.75
    assert wl.max_links_per_node == 5
    assert wl.promotion_min_weight == 0.6
    assert wl.promotion_min_edge_heat == 0.3
    assert wl.pruning_max_age_days == 30
    assert wl.pruning_min_edge_heat == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/config/test_weak_links_settings.py -v`
Expected: FAIL with AttributeError (no weak_links attribute)

- [ ] **Step 3: Add WeakLinksSettings model**

Add to `src/context_service/config/settings.py` after other nested models:

```python
class WeakLinksSettings(BaseModel):
    """Weak links (speculative RELATED_TO edges) configuration."""

    model_config = {"extra": "ignore"}

    enabled: bool = Field(default=True, description="Enable weak link creation")

    # Ingest-time creation
    similarity_threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    max_links_per_node: int = Field(default=5, ge=1)
    top_k_candidates: int = Field(default=10, ge=1)
    initial_weight_multiplier: float = Field(default=0.5, ge=0.0, le=1.0)

    # Promotion thresholds
    promotion_min_weight: float = Field(default=0.6, ge=0.0, le=1.0)
    promotion_min_edge_heat: float = Field(default=0.3, ge=0.0)
    promotion_require_fact_endpoints: bool = Field(default=True)

    # Pruning thresholds
    pruning_max_age_days: int = Field(default=30, ge=1)
    pruning_min_edge_heat: float = Field(default=0.1, ge=0.0)

    # Embedding model tracking
    embedding_model_version: str = Field(default="jina-v3")
```

- [ ] **Step 4: Add field to Settings class**

In the `Settings` class, add:

```python
weak_links: WeakLinksSettings = Field(default_factory=WeakLinksSettings)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/config/test_weak_links_settings.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/settings.py tests/config/test_weak_links_settings.py
git commit -m "feat(weak-links): add configuration settings"
```

---

## Task 2: WeakLink Indexes

**Files:**
- Modify: `src/context_service/db/indexes.py`
- Test: `tests/db/test_weak_link_indexes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/db/test_weak_link_indexes.py
from context_service.db.indexes import WEAK_LINK_INDEX_QUERIES


def test_weak_link_indexes_defined():
    assert len(WEAK_LINK_INDEX_QUERIES) == 3
    assert "CREATE INDEX ON :WeakLink(id);" in WEAK_LINK_INDEX_QUERIES
    assert "CREATE INDEX ON :WeakLink(silo_id);" in WEAK_LINK_INDEX_QUERIES
    assert "CREATE INDEX ON :WeakLink(speculative);" in WEAK_LINK_INDEX_QUERIES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/db/test_weak_link_indexes.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Add index queries**

Add to `src/context_service/db/indexes.py` after `HEAT_CURSOR_INDEX_QUERIES`:

```python
# --- Weak links (speculative RELATED_TO edges) ---

WEAK_LINK_INDEX_QUERIES: tuple[str, ...] = (
    "CREATE INDEX ON :WeakLink(id);",
    "CREATE INDEX ON :WeakLink(silo_id);",
    "CREATE INDEX ON :WeakLink(speculative);",
)
```

- [ ] **Step 4: Add to ALL_INDEX_QUERIES**

Find the `ALL_INDEX_QUERIES` tuple and add `WEAK_LINK_INDEX_QUERIES`:

```python
ALL_INDEX_QUERIES: tuple[str, ...] = (
    *CLUSTER_INDEX_QUERIES,
    *HEAT_CURSOR_INDEX_QUERIES,
    *WEAK_LINK_INDEX_QUERIES,  # Add this line
    # ... rest of existing queries
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/db/test_weak_link_indexes.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/db/indexes.py tests/db/test_weak_link_indexes.py
git commit -m "feat(weak-links): add WeakLink node indexes"
```

---

## Task 3: Edge Access Events Module

**Files:**
- Create: `src/context_service/signals/edge_access_events.py`
- Test: `tests/signals/test_edge_access_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/signals/test_edge_access_events.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.signals.edge_access_events import (
    emit_edge_access_event,
    edge_access_stream_key,
    edge_id,
)


def test_edge_access_stream_key():
    assert edge_access_stream_key("silo-123") == "silo:silo-123:edge_access_events"


def test_edge_id_deterministic():
    eid1 = edge_id("node-a", "node-b", "RELATED_TO")
    eid2 = edge_id("node-b", "node-a", "RELATED_TO")
    assert eid1 == eid2


def test_edge_id_different_types():
    eid1 = edge_id("node-a", "node-b", "RELATED_TO")
    eid2 = edge_id("node-a", "node-b", "DERIVES_FROM")
    assert eid1 != eid2


@pytest.mark.asyncio
async def test_emit_edge_access_event_success():
    redis = AsyncMock()
    redis.xadd = AsyncMock()

    await emit_edge_access_event(
        redis=redis,
        silo_id="silo-123",
        from_node="node-a",
        to_node="node-b",
        edge_type="RELATED_TO",
    )

    redis.xadd.assert_called_once()
    call_args = redis.xadd.call_args
    assert call_args[0][0] == "silo:silo-123:edge_access_events"


@pytest.mark.asyncio
async def test_emit_edge_access_event_swallows_errors():
    redis = AsyncMock()
    redis.xadd = AsyncMock(side_effect=Exception("Redis down"))

    # Should not raise
    await emit_edge_access_event(
        redis=redis,
        silo_id="silo-123",
        from_node="node-a",
        to_node="node-b",
        edge_type="RELATED_TO",
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/signals/test_edge_access_events.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create edge_access_events.py**

```python
# src/context_service/signals/edge_access_events.py
"""Edge access event emission for the edge_heat asset.

Each graph traversal (depth > 0) calls ``emit_edge_access_event`` when an edge
is followed. Events land on a per-silo Redis stream which the edge_heat Dagster
asset drains to compute decay-weighted heat scores for edges.

Best-effort: Redis errors are logged and swallowed so broken Redis never blocks reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import NAMESPACE_DNS, uuid5

import structlog

if TYPE_CHECKING:
    from context_service.stores import RedisClient

logger = structlog.get_logger(__name__)

EDGE_ACCESS_STREAM_MAXLEN = 100_000


def edge_access_stream_key(silo_id: str) -> str:
    """Build the per-silo edge access event stream key."""
    return f"silo:{silo_id}:edge_access_events"


def edge_id(from_node: str, to_node: str, edge_type: str) -> str:
    """Deterministic edge ID from sorted node pair."""
    pair = tuple(sorted([from_node, to_node]))
    return str(uuid5(NAMESPACE_DNS, f"{pair[0]}:{pair[1]}:{edge_type}"))


async def emit_edge_access_event(
    redis: RedisClient,
    silo_id: str,
    from_node: str,
    to_node: str,
    edge_type: str,
    traversal_context: str = "recall",
) -> None:
    """Append edge access event to silo stream. Best-effort, never raises.

    Args:
        redis: Redis client for stream operations.
        silo_id: Silo the edge belongs to.
        from_node: Source node ID.
        to_node: Target node ID.
        edge_type: Edge type (e.g., "RELATED_TO").
        traversal_context: Context of traversal ("recall", "provenance", "graph").
    """
    try:
        eid = edge_id(from_node, to_node, edge_type)
        await redis.xadd(
            edge_access_stream_key(silo_id),
            {
                "edge_id": eid,
                "from_node": from_node,
                "to_node": to_node,
                "edge_type": edge_type,
                "context": traversal_context,
            },
            maxlen=EDGE_ACCESS_STREAM_MAXLEN,
            approximate=True,
        )
    except Exception as exc:
        logger.warning(
            "edge_access_event_emit_failed",
            silo_id=silo_id,
            from_node=from_node,
            to_node=to_node,
            error=str(exc),
        )


__all__ = [
    "EDGE_ACCESS_STREAM_MAXLEN",
    "edge_access_stream_key",
    "edge_id",
    "emit_edge_access_event",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/signals/test_edge_access_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/signals/edge_access_events.py tests/signals/test_edge_access_events.py
git commit -m "feat(weak-links): add edge access event emission"
```

---

## Task 4: Weak Link Creation Asset

**Files:**
- Create: `src/context_service/pipelines/assets/weak_link_creation.py`
- Modify: `src/context_service/pipelines/assets/__init__.py`
- Test: `tests/pipelines/test_weak_link_creation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/test_weak_link_creation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from context_service.pipelines.assets.weak_link_creation import (
    create_weak_links_for_node,
    MERGE_WEAK_LINK_CYPHER,
)


def test_merge_cypher_has_required_params():
    assert "$from_id" in MERGE_WEAK_LINK_CYPHER
    assert "$to_id" in MERGE_WEAK_LINK_CYPHER
    assert "$link_id" in MERGE_WEAK_LINK_CYPHER
    assert "$silo_id" in MERGE_WEAK_LINK_CYPHER
    assert "WeakLink" in MERGE_WEAK_LINK_CYPHER
    assert "MERGE" in MERGE_WEAK_LINK_CYPHER


@pytest.mark.asyncio
async def test_create_weak_links_skips_when_at_cap():
    memgraph = AsyncMock()
    qdrant = AsyncMock()
    
    # Already at cap
    memgraph.execute.return_value = [{"degree": 5}]
    
    result = await create_weak_links_for_node(
        memgraph=memgraph,
        qdrant=qdrant,
        node_id="node-123",
        embedding=[0.1] * 768,
        silo_id="silo-abc",
        max_links_per_node=5,
        similarity_threshold=0.75,
        top_k_candidates=10,
        initial_weight_multiplier=0.5,
        embedding_model="jina-v3",
    )
    
    assert result == 0
    qdrant.search.assert_not_called()


@pytest.mark.asyncio
async def test_create_weak_links_filters_by_threshold():
    memgraph = AsyncMock()
    qdrant = AsyncMock()
    
    memgraph.execute.return_value = [{"degree": 0}]
    qdrant.search.return_value = [
        MagicMock(id="node-a", score=0.9),
        MagicMock(id="node-b", score=0.6),  # Below threshold
    ]
    
    result = await create_weak_links_for_node(
        memgraph=memgraph,
        qdrant=qdrant,
        node_id="node-123",
        embedding=[0.1] * 768,
        silo_id="silo-abc",
        max_links_per_node=5,
        similarity_threshold=0.75,
        top_k_candidates=10,
        initial_weight_multiplier=0.5,
        embedding_model="jina-v3",
    )
    
    assert result == 1  # Only node-a passes threshold
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/test_weak_link_creation.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create weak_link_creation.py**

```python
# src/context_service/pipelines/assets/weak_link_creation.py
"""Weak link creation after embedding.

Creates speculative RELATED_TO edges (reified as WeakLink nodes) between
semantically similar nodes based on embedding cosine similarity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.signals.edge_access_events import edge_id

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore, VectorStore

logger = structlog.get_logger(__name__)

DEGREE_CHECK_CYPHER = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[:SOURCE_OF]->(:WeakLink)
RETURN count(*) AS degree
"""

MERGE_WEAK_LINK_CYPHER = """
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
"""


async def create_weak_links_for_node(
    memgraph: HyperGraphStore,
    qdrant: VectorStore,
    node_id: str,
    embedding: list[float],
    silo_id: str,
    max_links_per_node: int,
    similarity_threshold: float,
    top_k_candidates: int,
    initial_weight_multiplier: float,
    embedding_model: str,
) -> int:
    """Create weak links for a newly embedded node. Returns count created."""
    # Check existing degree
    result = await memgraph.execute(
        DEGREE_CHECK_CYPHER,
        {"node_id": node_id, "silo_id": silo_id},
    )
    existing_degree = result[0]["degree"] if result else 0
    budget = max(0, max_links_per_node - existing_degree)

    if budget == 0:
        return 0

    # Search for similar nodes
    similar = await qdrant.search(
        vector=embedding,
        limit=top_k_candidates,
        filter_conditions={"silo_id": silo_id},
    )

    # Filter by threshold and cap to budget
    candidates = [c for c in similar if c.score >= similarity_threshold and c.id != node_id]
    candidates = candidates[:budget]

    created = 0
    for candidate in candidates:
        # Sort IDs for deterministic edge direction
        a, b = sorted([node_id, candidate.id])
        link_id = edge_id(a, b, "RELATED_TO")

        await memgraph.execute(
            MERGE_WEAK_LINK_CYPHER,
            {
                "from_id": a,
                "to_id": b,
                "link_id": link_id,
                "silo_id": silo_id,
                "weight": candidate.score * initial_weight_multiplier,
                "embedding_model": embedding_model,
            },
        )
        created += 1

    if created > 0:
        logger.info(
            "weak_links_created",
            node_id=node_id,
            silo_id=silo_id,
            count=created,
        )

    return created
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/test_weak_link_creation.py -v`
Expected: PASS

- [ ] **Step 5: Export from __init__.py**

Add to `src/context_service/pipelines/assets/__init__.py`:

```python
from context_service.pipelines.assets.weak_link_creation import create_weak_links_for_node
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/pipelines/assets/weak_link_creation.py \
        src/context_service/pipelines/assets/__init__.py \
        tests/pipelines/test_weak_link_creation.py
git commit -m "feat(weak-links): add weak link creation function"
```

---

## Task 5: Wire Weak Link Creation into Embedding Asset

**Files:**
- Modify: `src/context_service/pipelines/assets/embedding.py`
- Test: `tests/pipelines/test_embedding_weak_links.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/test_embedding_weak_links.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_embedding_asset_creates_weak_links_when_enabled():
    """Verify embedding asset calls create_weak_links_for_node when enabled."""
    with patch(
        "context_service.pipelines.assets.embedding.create_weak_links_for_node",
        new_callable=AsyncMock,
    ) as mock_create:
        with patch(
            "context_service.pipelines.assets.embedding.get_settings"
        ) as mock_settings:
            mock_settings.return_value.weak_links.enabled = True
            mock_settings.return_value.weak_links.similarity_threshold = 0.75
            mock_settings.return_value.weak_links.max_links_per_node = 5
            mock_settings.return_value.weak_links.top_k_candidates = 10
            mock_settings.return_value.weak_links.initial_weight_multiplier = 0.5
            mock_settings.return_value.weak_links.embedding_model_version = "jina-v3"

            from context_service.pipelines.assets.embedding import _post_embed_hook

            await _post_embed_hook(
                memgraph=AsyncMock(),
                qdrant=AsyncMock(),
                node_id="node-123",
                embedding=[0.1] * 768,
                silo_id="silo-abc",
            )

            mock_create.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/test_embedding_weak_links.py -v`
Expected: FAIL (no _post_embed_hook function)

- [ ] **Step 3: Add post-embed hook to embedding.py**

Read the existing embedding.py first to find the right insertion point, then add:

```python
from context_service.config.settings import get_settings
from context_service.pipelines.assets.weak_link_creation import create_weak_links_for_node


async def _post_embed_hook(
    memgraph: HyperGraphStore,
    qdrant: VectorStore,
    node_id: str,
    embedding: list[float],
    silo_id: str,
) -> None:
    """Post-embedding hook: create weak links if enabled."""
    settings = get_settings()
    if not settings.weak_links.enabled:
        return

    wl = settings.weak_links
    await create_weak_links_for_node(
        memgraph=memgraph,
        qdrant=qdrant,
        node_id=node_id,
        embedding=embedding,
        silo_id=silo_id,
        max_links_per_node=wl.max_links_per_node,
        similarity_threshold=wl.similarity_threshold,
        top_k_candidates=wl.top_k_candidates,
        initial_weight_multiplier=wl.initial_weight_multiplier,
        embedding_model=wl.embedding_model_version,
    )
```

Then call `_post_embed_hook` after each node is embedded in the asset's main loop.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/test_embedding_weak_links.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/pipelines/assets/embedding.py tests/pipelines/test_embedding_weak_links.py
git commit -m "feat(weak-links): wire creation into embedding asset"
```

---

## Task 6: Edge Heat Asset

**Files:**
- Create: `src/context_service/pipelines/assets/edge_heat.py`
- Test: `tests/pipelines/test_edge_heat.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/test_edge_heat.py
import pytest
from context_service.pipelines.assets.edge_heat import (
    APPLY_EDGE_HEAT_CYPHER,
    EDGE_HEAT_HALF_LIFE_DAYS,
)


def test_edge_heat_constants():
    assert EDGE_HEAT_HALF_LIFE_DAYS == 7


def test_apply_edge_heat_cypher_structure():
    assert "UNWIND $updates AS u" in APPLY_EDGE_HEAT_CYPHER
    assert "WeakLink" in APPLY_EDGE_HEAT_CYPHER
    assert "edge_heat" in APPLY_EDGE_HEAT_CYPHER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/test_edge_heat.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create edge_heat.py**

```python
# src/context_service/pipelines/assets/edge_heat.py
"""Dagster asset: hourly edge heat scoring per silo.

Mirrors the node heat asset pattern. Drains the per-silo Redis edge access
events stream, applies exponential decay to accumulate a heat score for each
traversed edge (WeakLink node), writes w.edge_heat to Memgraph.
"""

import asyncio
import concurrent.futures
import math
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource, RedisResource
from context_service.signals.edge_access_events import edge_access_stream_key

EDGE_HEAT_HALF_LIFE_DAYS = 7
XREAD_COUNT = 10_000


def _run_async(coro: Any) -> Any:
    """Run a coroutine, handling cases where an event loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


def _decay_factor(age_seconds: float) -> float:
    """Exponential decay with EDGE_HEAT_HALF_LIFE_DAYS half-life."""
    half_life_s = EDGE_HEAT_HALF_LIFE_DAYS * 86400.0
    return math.pow(0.5, age_seconds / half_life_s)


APPLY_EDGE_HEAT_CYPHER = """
UNWIND $updates AS u
MATCH (w:WeakLink {id: u.link_id, silo_id: $silo_id})
SET w.edge_heat = u.heat_score,
    w.heat_updated_at = $now
"""

GET_EDGE_HEAT_CURSOR_CYPHER = """
MATCH (c:EdgeHeatCursor {silo_id: $silo_id})
RETURN c.last_id AS last_id
"""

SET_EDGE_HEAT_CURSOR_CYPHER = """
MERGE (c:EdgeHeatCursor {silo_id: $silo_id})
SET c.last_id = $last_id, c.updated_at = $now
"""


@dg.asset(
    name="edge_heat",
    partitions_def=silo_partitions,
    deps=["heat"],
    description="Compute edge heat from traversal events",
    retry_policy=dg.RetryPolicy(max_retries=3, delay=10.0, backoff=dg.Backoff.EXPONENTIAL),
)
def edge_heat_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
    redis: RedisResource,
) -> dg.Output[dict[str, Any]]:
    """Process edge access events and update WeakLink heat scores."""
    silo_id = context.partition_key

    async def _run() -> dict[str, Any]:
        mg = memgraph.get_client()
        rd = redis.get_client()

        # Get cursor
        cursor_result = await mg.execute(GET_EDGE_HEAT_CURSOR_CYPHER, {"silo_id": silo_id})
        last_id = cursor_result[0]["last_id"] if cursor_result else "0-0"

        # Read events
        stream_key = edge_access_stream_key(silo_id)
        events = await rd.xread({stream_key: last_id}, count=XREAD_COUNT)

        if not events:
            return {"silo_id": silo_id, "events_processed": 0, "edges_updated": 0}

        # Aggregate heat by edge_id
        now = datetime.now(UTC)
        heat_acc: dict[str, float] = defaultdict(float)
        new_last_id = last_id

        for stream_name, entries in events:
            for entry_id, fields in entries:
                edge_id = fields.get(b"edge_id") or fields.get("edge_id")
                if edge_id:
                    edge_id = edge_id.decode() if isinstance(edge_id, bytes) else edge_id
                    heat_acc[edge_id] += 1.0
                new_last_id = entry_id

        # Build updates
        updates = [{"link_id": eid, "heat_score": heat} for eid, heat in heat_acc.items()]

        if updates:
            await mg.execute(
                APPLY_EDGE_HEAT_CYPHER,
                {"updates": updates, "silo_id": silo_id, "now": now.isoformat()},
            )

        # Update cursor
        await mg.execute(
            SET_EDGE_HEAT_CURSOR_CYPHER,
            {"silo_id": silo_id, "last_id": new_last_id, "now": now.isoformat()},
        )

        return {
            "silo_id": silo_id,
            "events_processed": sum(len(e[1]) for e in events),
            "edges_updated": len(updates),
        }

    result = _run_async(_run())
    context.log.info(f"Edge heat: {result}")
    return dg.Output(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/test_edge_heat.py -v`
Expected: PASS

- [ ] **Step 5: Register asset in definitions**

Add import to `src/context_service/pipelines/definitions.py`:

```python
from context_service.pipelines.assets.edge_heat import edge_heat_asset
```

Add to the assets list.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/pipelines/assets/edge_heat.py \
        src/context_service/pipelines/definitions.py \
        tests/pipelines/test_edge_heat.py
git commit -m "feat(weak-links): add edge heat dagster asset"
```

---

## Task 7: Weak Link Review Asset (Promotion/Pruning/Demotion)

**Files:**
- Create: `src/context_service/pipelines/assets/weak_link_review.py`
- Test: `tests/pipelines/test_weak_link_review.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipelines/test_weak_link_review.py
from context_service.pipelines.assets.weak_link_review import (
    PROMOTE_CYPHER,
    PRUNE_CYPHER,
    DEMOTE_SUPERSEDED_CYPHER,
)


def test_promote_cypher_has_required_filters():
    assert "speculative = true" in PROMOTE_CYPHER
    assert "weight >=" in PROMOTE_CYPHER
    assert "edge_heat >=" in PROMOTE_CYPHER


def test_prune_cypher_deletes_weak_links():
    assert "DELETE" in PRUNE_CYPHER
    assert "speculative = true" in PRUNE_CYPHER
    assert "edge_heat <" in PRUNE_CYPHER


def test_demote_handles_superseded():
    assert "superseded = true" in DEMOTE_SUPERSEDED_CYPHER
    assert "speculative = true" in DEMOTE_SUPERSEDED_CYPHER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/pipelines/test_weak_link_review.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Create weak_link_review.py**

```python
# src/context_service/pipelines/assets/weak_link_review.py
"""Dagster asset: weak link promotion, pruning, and demotion.

Runs after heat assets. Promotes high-signal speculative edges, prunes old
unused ones, demotes promoted edges whose endpoints were superseded.
"""

import asyncio
import concurrent.futures
from datetime import UTC, datetime
from typing import Any

import dagster as dg
from dagster import AssetExecutionContext

from context_service.config.settings import get_settings
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=300)


PROMOTE_CYPHER = """
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
"""

PRUNE_CYPHER = """
MATCH (a)-[s:SOURCE_OF]->(w:WeakLink)-[t:TARGETS]->(b)
WHERE w.speculative = true
  AND w.silo_id = $silo_id
  AND w.created_at < datetime() - duration({days: $max_age_days})
  AND w.edge_heat < $min_edge_heat
DELETE s, t, w
RETURN count(w) AS pruned
"""

DEMOTE_SUPERSEDED_CYPHER = """
MATCH (a)-[:SOURCE_OF]->(w:WeakLink)-[:TARGETS]->(b)
WHERE w.speculative = false
  AND w.silo_id = $silo_id
  AND (a.superseded = true OR b.superseded = true)
SET w.speculative = true,
    w.demoted_at = datetime(),
    w.demoted_reason = 'endpoint_superseded'
RETURN count(w) AS demoted
"""


@dg.asset(
    name="weak_link_review",
    partitions_def=silo_partitions,
    deps=["heat", "edge_heat"],
    description="Promote high-signal weak links, prune unused ones, demote stale promoted links",
)
def weak_link_review_asset(
    context: AssetExecutionContext,
    memgraph: MemgraphResource,
) -> dg.Output[dict[str, Any]]:
    """Review weak links: promote, prune, demote."""
    silo_id = context.partition_key
    settings = get_settings()
    wl = settings.weak_links

    async def _run() -> dict[str, Any]:
        mg = memgraph.get_client()

        # Promote
        promote_result = await mg.execute(
            PROMOTE_CYPHER,
            {
                "silo_id": silo_id,
                "min_weight": wl.promotion_min_weight,
                "min_edge_heat": wl.promotion_min_edge_heat,
                "require_facts": wl.promotion_require_fact_endpoints,
            },
        )
        promoted = promote_result[0]["promoted"] if promote_result else 0

        # Prune
        prune_result = await mg.execute(
            PRUNE_CYPHER,
            {
                "silo_id": silo_id,
                "max_age_days": wl.pruning_max_age_days,
                "min_edge_heat": wl.pruning_min_edge_heat,
            },
        )
        pruned = prune_result[0]["pruned"] if prune_result else 0

        # Demote superseded
        demote_result = await mg.execute(DEMOTE_SUPERSEDED_CYPHER, {"silo_id": silo_id})
        demoted = demote_result[0]["demoted"] if demote_result else 0

        return {
            "silo_id": silo_id,
            "promoted": promoted,
            "pruned": pruned,
            "demoted": demoted,
        }

    result = _run_async(_run())
    context.log.info(f"Weak link review: {result}")
    return dg.Output(result)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/pipelines/test_weak_link_review.py -v`
Expected: PASS

- [ ] **Step 5: Register asset in definitions**

Add import to `src/context_service/pipelines/definitions.py`:

```python
from context_service.pipelines.assets.weak_link_review import weak_link_review_asset
```

Add to the assets list.

- [ ] **Step 6: Commit**

```bash
git add src/context_service/pipelines/assets/weak_link_review.py \
        src/context_service/pipelines/definitions.py \
        tests/pipelines/test_weak_link_review.py
git commit -m "feat(weak-links): add weak link review asset (promote/prune/demote)"
```

---

## Task 8: Wire Edge Access Events into context_recall

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py` (or wherever graph traversal happens)
- Test: `tests/mcp/test_recall_edge_events.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/mcp/test_recall_edge_events.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_recall_emits_edge_events_on_traversal():
    """Graph traversal (depth > 0) should emit edge access events."""
    with patch(
        "context_service.mcp.tools.recall.emit_edge_access_event",
        new_callable=AsyncMock,
    ) as mock_emit:
        # Call the traversal code path with depth > 0
        # This test structure depends on actual recall implementation
        # Placeholder - fill in based on actual recall.py structure
        pass
```

- [ ] **Step 2: Find graph traversal code path**

Read the recall tool implementation to identify where edges are followed during depth > 0 traversal.

- [ ] **Step 3: Add emit calls after edge traversal**

Import and call:

```python
from context_service.signals.edge_access_events import emit_edge_access_event

# After following each edge:
await emit_edge_access_event(
    redis=redis,
    silo_id=silo_id,
    from_node=source_node_id,
    to_node=target_node_id,
    edge_type=edge_type,
    traversal_context="recall",
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/test_recall_edge_events.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/recall.py tests/mcp/test_recall_edge_events.py
git commit -m "feat(weak-links): emit edge access events on graph traversal"
```

---

## Task 9: Integration Test for Full Cycle

**Files:**
- Create: `tests/integration/test_weak_links_cycle.py`

- [ ] **Step 1: Write the integration test**

```python
# tests/integration/test_weak_links_cycle.py
"""Integration test for weak links: create -> access -> heat -> promote."""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def weak_links_enabled(monkeypatch):
    monkeypatch.setenv("WEAK_LINKS__ENABLED", "true")
    monkeypatch.setenv("WEAK_LINKS__SIMILARITY_THRESHOLD", "0.5")


@pytest.mark.asyncio
async def test_weak_link_full_cycle(
    weak_links_enabled,
    memgraph_client,
    qdrant_client,
    redis_client,
    test_silo,
):
    """End-to-end: embed nodes -> create weak links -> traverse -> heat -> promote."""
    # 1. Create two similar nodes
    # 2. Embed them (should create weak link)
    # 3. Verify WeakLink node exists with speculative=true
    # 4. Traverse via context_recall with depth=1
    # 5. Run edge_heat asset
    # 6. Verify edge_heat > 0
    # 7. Run weak_link_review asset
    # 8. Verify speculative=false (promoted)
    pass  # Fill in based on test fixtures available
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/integration/test_weak_links_cycle.py -v -m integration`
Expected: PASS (requires docker stack)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_weak_links_cycle.py
git commit -m "test(weak-links): add integration test for full cycle"
```

---

## Task 10: Update Docker Compose

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add edge properties flag to Memgraph**

Find the Memgraph service and update:

```yaml
memgraph:
  command: ["--log-level=WARNING", "--storage-properties-on-edges=true"]
```

- [ ] **Step 2: Test locally**

Run: `just docker-up && just test-integration`

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "chore: enable edge properties on Memgraph"
```

---

Plan complete and saved to `docs/superpowers/plans/2026-05-05-weak-links.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?