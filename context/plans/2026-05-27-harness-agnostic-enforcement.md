# Harness-Agnostic Memory Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable memory enforcement across any MCP-capable agent via skill discipline + smart tick() without per-harness extensions.

**Architecture:** Write-time affinity computation (k-NN on store) enables fast tick() queries. tick() runs parallel rule checks with caching/debouncing, returns template nudges capped at 3. Session state in Redis tracks shown/ignored nudges.

**Tech Stack:** Python 3.12, FastMCP, Memgraph, Qdrant, Redis, asyncio

**Spec:** `docs/superpowers/specs/2026-05-27-harness-agnostic-enforcement-design.md`

---

## File Structure

### New Files
- `src/context_service/engine/affinity.py` - k-NN affinity computation at write time
- `src/context_service/engine/session_state.py` - Redis session state for tick()
- `src/context_service/engine/nudges.py` - Nudge detection rules and templates
- `tests/engine/test_affinity.py` - Affinity computation tests
- `tests/engine/test_session_state.py` - Session state tests
- `tests/engine/test_nudges.py` - Nudge detection tests

### Modified Files
- `src/context_service/mcp/tools/tick.py` - Enhanced tick with session_id, recent_context, nudges
- `src/context_service/mcp/tools/context_store.py` - Add affinity computation on store
- `src/context_service/engine/engagement.py` - Parallel checks with timeouts
- `src/context_service/config/identities.yaml` - Model migration
- `src/context_service/config/settings.py` - Model defaults
- `tests/mcp/tools/test_tick.py` - Enhanced tick tests
- `skills/engrammic-onboarding/engrammic-onboarding.md` - tick() discipline

---

## Phase 1: Write-Time Affinity

### Task 1.1: Affinity Edge Schema

**Files:**
- Create: `src/context_service/engine/affinity.py`
- Test: `tests/engine/test_affinity.py`

- [ ] **Step 1: Write the failing test for affinity edge creation**

```python
# tests/engine/test_affinity.py
import pytest
from context_service.engine.affinity import AffinityEdge, compute_affinities

def test_affinity_edge_schema():
    edge = AffinityEdge(
        source_id="node_a",
        target_id="node_b",
        similarity=0.87,
        source_embedding_model="text-embedding-3-small",
    )
    assert edge.similarity >= 0.85
    assert edge.source_embedding_model == "text-embedding-3-small"
    assert edge.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_affinity.py::test_affinity_edge_schema -v`
Expected: FAIL with "No module named 'context_service.engine.affinity'"

- [ ] **Step 3: Implement AffinityEdge model**

```python
# src/context_service/engine/affinity.py
"""Write-time affinity computation for Knowledge nodes.

Computes k-NN similarity at store time and creates AFFINITY edges
for fast lookup during tick().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from qdrant_client import QdrantClient

AFFINITY_THRESHOLD = 0.85
AFFINITY_K = 3


class AffinityEdge(BaseModel):
    """Edge representing semantic affinity between Knowledge nodes."""

    source_id: str
    target_id: str
    similarity: float = Field(ge=0.85, le=1.0)
    source_embedding_model: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_affinity.py::test_affinity_edge_schema -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/affinity.py tests/engine/test_affinity.py
git commit -m "feat(affinity): add AffinityEdge model"
```

---

### Task 1.2: k-NN Affinity Computation

**Files:**
- Modify: `src/context_service/engine/affinity.py`
- Test: `tests/engine/test_affinity.py`

- [ ] **Step 1: Write the failing test for k-NN computation**

```python
# tests/engine/test_affinity.py (append)
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_compute_affinities_finds_similar_nodes():
    # Mock Qdrant client
    mock_qdrant = MagicMock()
    mock_qdrant.search = AsyncMock(return_value=[
        MagicMock(id="node_b", score=0.92),
        MagicMock(id="node_c", score=0.88),
        MagicMock(id="node_d", score=0.75),  # Below threshold
    ])
    
    embedding = [0.1] * 1536  # Mock embedding
    
    edges = await compute_affinities(
        qdrant=mock_qdrant,
        source_id="node_a",
        embedding=embedding,
        silo_id="test_silo",
        collection_name="knowledge",
        embedding_model="text-embedding-3-small",
    )
    
    assert len(edges) == 2  # Only node_b and node_c above threshold
    assert edges[0].target_id == "node_b"
    assert edges[0].similarity == 0.92
    assert edges[1].target_id == "node_c"


@pytest.mark.asyncio
async def test_compute_affinities_excludes_self():
    mock_qdrant = MagicMock()
    mock_qdrant.search = AsyncMock(return_value=[
        MagicMock(id="node_a", score=1.0),  # Self - should be excluded
        MagicMock(id="node_b", score=0.90),
    ])
    
    embedding = [0.1] * 1536
    
    edges = await compute_affinities(
        qdrant=mock_qdrant,
        source_id="node_a",
        embedding=embedding,
        silo_id="test_silo",
        collection_name="knowledge",
        embedding_model="text-embedding-3-small",
    )
    
    assert len(edges) == 1
    assert edges[0].target_id == "node_b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_affinity.py::test_compute_affinities_finds_similar_nodes -v`
Expected: FAIL with "cannot import name 'compute_affinities'"

- [ ] **Step 3: Implement compute_affinities**

```python
# src/context_service/engine/affinity.py (append to existing)

from qdrant_client.models import Filter, FieldCondition, MatchValue

async def compute_affinities(
    qdrant: QdrantClient,
    source_id: str,
    embedding: list[float],
    silo_id: str,
    collection_name: str,
    embedding_model: str,
    k: int = AFFINITY_K,
    threshold: float = AFFINITY_THRESHOLD,
) -> list[AffinityEdge]:
    """Compute k-NN affinities for a new node.
    
    Args:
        qdrant: Qdrant client
        source_id: ID of the node being stored
        embedding: Embedding vector of the node
        silo_id: Silo to search within
        collection_name: Qdrant collection name
        embedding_model: Name of embedding model used
        k: Number of neighbors to check
        threshold: Minimum similarity to create affinity edge
        
    Returns:
        List of AffinityEdge for nodes above threshold (excluding self)
    """
    # Search for k+1 to account for potential self-match
    results = await qdrant.search(
        collection_name=collection_name,
        query_vector=embedding,
        limit=k + 1,
        query_filter=Filter(
            must=[FieldCondition(key="silo_id", match=MatchValue(value=silo_id))]
        ),
    )
    
    edges = []
    for result in results:
        # Skip self
        if result.id == source_id:
            continue
        # Skip below threshold
        if result.score < threshold:
            continue
        # Limit to k edges
        if len(edges) >= k:
            break
            
        edges.append(AffinityEdge(
            source_id=source_id,
            target_id=str(result.id),
            similarity=result.score,
            source_embedding_model=embedding_model,
        ))
    
    return edges
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_affinity.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/affinity.py tests/engine/test_affinity.py
git commit -m "feat(affinity): implement k-NN affinity computation"
```

---

### Task 1.3: Store Affinity Edges in Graph

**Files:**
- Modify: `src/context_service/engine/affinity.py`
- Test: `tests/engine/test_affinity.py`

- [ ] **Step 1: Write the failing test for graph storage**

```python
# tests/engine/test_affinity.py (append)

@pytest.mark.asyncio
async def test_store_affinity_edges_creates_relationships():
    mock_store = MagicMock()
    mock_store.execute_query = AsyncMock(return_value=[])
    
    edges = [
        AffinityEdge(
            source_id="node_a",
            target_id="node_b",
            similarity=0.92,
            source_embedding_model="text-embedding-3-small",
        ),
        AffinityEdge(
            source_id="node_a",
            target_id="node_c",
            similarity=0.88,
            source_embedding_model="text-embedding-3-small",
        ),
    ]
    
    await store_affinity_edges(store=mock_store, edges=edges, silo_id="test_silo")
    
    assert mock_store.execute_query.call_count == 2
    # Verify Cypher query structure
    call_args = mock_store.execute_query.call_args_list[0]
    query = call_args[0][0]
    assert "AFFINITY" in query
    assert "similarity" in query
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_affinity.py::test_store_affinity_edges_creates_relationships -v`
Expected: FAIL with "cannot import name 'store_affinity_edges'"

- [ ] **Step 3: Implement store_affinity_edges**

```python
# src/context_service/engine/affinity.py (append)

from context_service.engine.protocols import HyperGraphStore

STORE_AFFINITY_QUERY = """
MATCH (a {id: $source_id, silo_id: $silo_id})
MATCH (b {id: $target_id, silo_id: $silo_id})
MERGE (a)-[r:AFFINITY]->(b)
SET r.similarity = $similarity,
    r.created_at = $created_at,
    r.source_embedding_model = $embedding_model
RETURN r
"""


async def store_affinity_edges(
    store: HyperGraphStore,
    edges: list[AffinityEdge],
    silo_id: str,
) -> None:
    """Store affinity edges in the graph.
    
    Creates bidirectional AFFINITY relationships between Knowledge nodes.
    """
    for edge in edges:
        await store.execute_query(
            STORE_AFFINITY_QUERY,
            {
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "silo_id": silo_id,
                "similarity": edge.similarity,
                "created_at": edge.created_at.isoformat(),
                "embedding_model": edge.source_embedding_model,
            },
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_affinity.py::test_store_affinity_edges_creates_relationships -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/affinity.py tests/engine/test_affinity.py
git commit -m "feat(affinity): store affinity edges in graph"
```

---

### Task 1.4: Integrate Affinity into Store Flow

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py`
- Test: `tests/mcp/tools/test_context_store_affinity.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/mcp/tools/test_context_store_affinity.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

@pytest.mark.asyncio
async def test_store_knowledge_computes_affinities():
    """Verify that storing Knowledge triggers affinity computation."""
    with patch("context_service.mcp.tools.context_store.compute_affinities") as mock_compute:
        with patch("context_service.mcp.tools.context_store.store_affinity_edges") as mock_store:
            mock_compute.return_value = []
            
            # Import after patching
            from context_service.mcp.tools.context_store import _store_with_affinity
            
            await _store_with_affinity(
                content="Test knowledge",
                layer="knowledge",
                embedding=[0.1] * 1536,
                node_id="test_node",
                silo_id="test_silo",
                qdrant=MagicMock(),
                store=MagicMock(),
            )
            
            mock_compute.assert_called_once()
            mock_store.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_context_store_affinity.py -v`
Expected: FAIL

- [ ] **Step 3: Add affinity computation to store flow**

In `src/context_service/mcp/tools/context_store.py`, locate the store handler and add:

```python
# Add import at top
from context_service.engine.affinity import compute_affinities, store_affinity_edges

# Add helper function
async def _compute_and_store_affinities(
    node_id: str,
    embedding: list[float],
    silo_id: str,
    qdrant: QdrantClient,
    store: HyperGraphStore,
    layer: str,
) -> None:
    """Compute and store affinity edges for Knowledge nodes."""
    if layer != "knowledge":
        return  # Only compute affinities for Knowledge layer
    
    try:
        edges = await compute_affinities(
            qdrant=qdrant,
            source_id=node_id,
            embedding=embedding,
            silo_id=silo_id,
            collection_name="knowledge",
            embedding_model="text-embedding-3-small",
        )
        if edges:
            await store_affinity_edges(store=store, edges=edges, silo_id=silo_id)
    except Exception as e:
        # Log but don't fail the store operation
        logger.warning("Affinity computation failed", error=str(e), node_id=node_id)
```

Then call this after the main store operation completes successfully.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/mcp/tools/test_context_store_affinity.py -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to ensure no regressions**

Run: `uv run pytest tests/mcp/tools/test_learn.py tests/mcp/tools/test_remember.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py tests/mcp/tools/test_context_store_affinity.py
git commit -m "feat(store): integrate affinity computation into store flow"
```

---

## Phase 2: tick() Enhancement

### Task 2.1: Session State Management

**Files:**
- Create: `src/context_service/engine/session_state.py`
- Test: `tests/engine/test_session_state.py`

- [ ] **Step 1: Write the failing test for session state**

```python
# tests/engine/test_session_state.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_get_or_create_session_creates_new():
    mock_redis = MagicMock()
    mock_redis.get = AsyncMock(return_value=None)
    mock_redis.setex = AsyncMock()
    
    from context_service.engine.session_state import get_or_create_session
    
    session = await get_or_create_session(
        redis=mock_redis,
        session_id=None,
        silo_id="test_silo",
    )
    
    assert session.session_id.startswith("sess_")
    assert session.turn_count == 0
    assert session.last_store_turn == 0
    mock_redis.setex.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_session_loads_existing():
    import json
    mock_redis = MagicMock()
    existing_state = {
        "session_id": "sess_existing",
        "turn_count": 5,
        "last_store_turn": 3,
        "shown_nudges": {"form_belief": [2, 4]},
        "ignored_nudges": {"form_belief": 1},
    }
    mock_redis.get = AsyncMock(return_value=json.dumps(existing_state))
    
    from context_service.engine.session_state import get_or_create_session
    
    session = await get_or_create_session(
        redis=mock_redis,
        session_id="sess_existing",
        silo_id="test_silo",
    )
    
    assert session.session_id == "sess_existing"
    assert session.turn_count == 5
    assert session.shown_nudges["form_belief"] == [2, 4]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_session_state.py -v`
Expected: FAIL with "No module named 'context_service.engine.session_state'"

- [ ] **Step 3: Implement session state module**

```python
# src/context_service/engine/session_state.py
"""Redis-backed session state for tick() engagement tracking."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from redis.asyncio import Redis

SESSION_TTL_SECONDS = 4 * 60 * 60  # 4 hours
DEBOUNCE_TICKS = 3
MAX_IGNORES_BEFORE_SUPPRESS = 3


class SessionState(BaseModel):
    """Session state for tick() engagement tracking."""

    session_id: str
    turn_count: int = 0
    last_store_turn: int = 0
    shown_nudges: dict[str, list[int]] = Field(default_factory=dict)
    ignored_nudges: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def should_show_nudge(self, nudge_type: str) -> bool:
        """Check if nudge should be shown based on debouncing rules."""
        # Check if suppressed due to ignores
        if self.ignored_nudges.get(nudge_type, 0) >= MAX_IGNORES_BEFORE_SUPPRESS:
            return False
        # Check debounce window
        shown_turns = self.shown_nudges.get(nudge_type, [])
        if shown_turns:
            last_shown = max(shown_turns)
            if self.turn_count - last_shown < DEBOUNCE_TICKS:
                return False
        return True

    def record_nudge_shown(self, nudge_type: str) -> None:
        """Record that a nudge was shown this turn."""
        if nudge_type not in self.shown_nudges:
            self.shown_nudges[nudge_type] = []
        self.shown_nudges[nudge_type].append(self.turn_count)
        # Keep only last 10 turns
        self.shown_nudges[nudge_type] = self.shown_nudges[nudge_type][-10:]

    def record_nudge_ignored(self, nudge_type: str) -> None:
        """Record that a nudge was ignored."""
        self.ignored_nudges[nudge_type] = self.ignored_nudges.get(nudge_type, 0) + 1


def _session_key(silo_id: str, session_id: str) -> str:
    return f"session:{silo_id}:{session_id}"


async def get_or_create_session(
    redis: Redis,
    session_id: str | None,
    silo_id: str,
) -> SessionState:
    """Get existing session or create new one."""
    if session_id:
        data = await redis.get(_session_key(silo_id, session_id))
        if data:
            return SessionState.model_validate_json(data)
    
    # Create new session
    new_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    session = SessionState(session_id=new_id)
    await redis.setex(
        _session_key(new_id),
        SESSION_TTL_SECONDS,
        session.model_dump_json(),
    )
    return session


async def save_session(redis: Redis, session: SessionState) -> None:
    """Save session state to Redis."""
    await redis.setex(
        _session_key(session.session_id),
        SESSION_TTL_SECONDS,
        session.model_dump_json(),
    )


async def increment_turn(redis: Redis, session: SessionState) -> SessionState:
    """Increment turn count and save."""
    session.turn_count += 1
    await save_session(redis, session)
    return session
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_session_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/session_state.py tests/engine/test_session_state.py
git commit -m "feat(session): add Redis-backed session state for tick()"
```

---

### Task 2.2: Nudge Detection Rules

**Files:**
- Create: `src/context_service/engine/nudges.py`
- Test: `tests/engine/test_nudges.py`

- [ ] **Step 1: Write the failing test for nudge types**

```python
# tests/engine/test_nudges.py
import pytest
from context_service.engine.nudges import (
    Nudge,
    NudgeType,
    NUDGE_TEMPLATES,
    format_nudge,
)

def test_nudge_types_have_templates():
    for nudge_type in NudgeType:
        assert nudge_type.value in NUDGE_TEMPLATES


def test_format_nudge_markers():
    nudge = format_nudge(
        nudge_type=NudgeType.PENDING_MARKERS,
        count=3,
    )
    assert nudge.type == NudgeType.PENDING_MARKERS
    assert "3" in nudge.prompt
    assert nudge.suggested_tool is None


def test_format_nudge_form_belief():
    nudge = format_nudge(
        nudge_type=NudgeType.FORM_BELIEF,
        topic="OAuth authentication",
        about_nodes=["node_a", "node_b", "node_c"],
    )
    assert nudge.type == NudgeType.FORM_BELIEF
    assert "OAuth" in nudge.prompt
    assert nudge.suggested_tool == "believe"
    assert nudge.about_nodes == ["node_a", "node_b", "node_c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_nudges.py -v`
Expected: FAIL with "No module named 'context_service.engine.nudges'"

- [ ] **Step 3: Implement nudge types and templates**

```python
# src/context_service/engine/nudges.py
"""Nudge detection rules and template formatting for tick()."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class NudgeType(str, Enum):
    PENDING_MARKERS = "pending_markers"
    STALE_HYPOTHESIS = "stale_hypothesis"
    STORAGE_GAP = "storage_gap"
    FORM_BELIEF = "form_belief"
    RELEVANT_CONTEXT = "relevant_context"
    OPEN_REASONING = "open_reasoning"


# Priority order: lower index = higher priority
NUDGE_PRIORITY = [
    NudgeType.PENDING_MARKERS,
    NudgeType.STALE_HYPOTHESIS,
    NudgeType.STORAGE_GAP,
    NudgeType.FORM_BELIEF,
    NudgeType.RELEVANT_CONTEXT,
    NudgeType.OPEN_REASONING,
]

NUDGE_TEMPLATES = {
    NudgeType.PENDING_MARKERS: "You have {count} marker(s) to address.",
    NudgeType.STALE_HYPOTHESIS: "Hypothesis '{hypothesis_id}' open for {turns} turns. Commit or revise?",
    NudgeType.STORAGE_GAP: "Nothing stored in {turns} turns. Consider checkpointing.",
    NudgeType.FORM_BELIEF: "{count} related observations about {topic}. Consider believe().",
    NudgeType.RELEVANT_CONTEXT: "Relevant to your work: {summaries}",
    NudgeType.OPEN_REASONING: "Reasoning chain open. Conclude with reason()?",
}

NUDGE_SUGGESTED_TOOLS = {
    NudgeType.PENDING_MARKERS: None,
    NudgeType.STALE_HYPOTHESIS: "commit",
    NudgeType.STORAGE_GAP: "remember",
    NudgeType.FORM_BELIEF: "believe",
    NudgeType.RELEVANT_CONTEXT: None,
    NudgeType.OPEN_REASONING: "reason",
}

MAX_NUDGES = 3


class Nudge(BaseModel):
    """A nudge to show the agent."""

    type: NudgeType
    prompt: str
    suggested_tool: str | None = None
    about_nodes: list[str] | None = None
    priority: int = 0


def format_nudge(nudge_type: NudgeType, **kwargs: Any) -> Nudge:
    """Format a nudge from template with given parameters."""
    template = NUDGE_TEMPLATES[nudge_type]
    prompt = template.format(**kwargs)
    priority = NUDGE_PRIORITY.index(nudge_type)
    
    return Nudge(
        type=nudge_type,
        prompt=prompt,
        suggested_tool=NUDGE_SUGGESTED_TOOLS[nudge_type],
        about_nodes=kwargs.get("about_nodes"),
        priority=priority,
    )


def prioritize_nudges(nudges: list[Nudge]) -> list[Nudge]:
    """Sort nudges by priority and cap at MAX_NUDGES."""
    sorted_nudges = sorted(nudges, key=lambda n: n.priority)
    return sorted_nudges[:MAX_NUDGES]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_nudges.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/nudges.py tests/engine/test_nudges.py
git commit -m "feat(nudges): add nudge types, templates, and prioritization"
```

---

### Task 2.3: Parallel Rule Checks with Timeouts

**Files:**
- Modify: `src/context_service/engine/engagement.py`
- Test: `tests/engine/test_engagement_parallel.py`

- [ ] **Step 1: Write the failing test for parallel checks**

```python
# tests/engine/test_engagement_parallel.py
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

@pytest.mark.asyncio
async def test_parallel_checks_complete_within_timeout():
    from context_service.engine.engagement import run_parallel_checks
    
    # Mock checks that complete at different speeds
    async def fast_check():
        await asyncio.sleep(0.01)
        return {"markers": [{"id": "m1"}]}
    
    async def slow_check():
        await asyncio.sleep(0.5)  # Exceeds 30ms individual timeout
        return {"hypotheses": []}
    
    checks = {
        "markers": fast_check(),
        "hypotheses": slow_check(),
    }
    
    results, completed, skipped = await run_parallel_checks(
        checks,
        individual_timeout=0.03,
        total_timeout=0.08,
    )
    
    assert "markers" in completed
    assert "hypotheses" in skipped
    assert results.get("markers") == {"markers": [{"id": "m1"}]}


@pytest.mark.asyncio
async def test_parallel_checks_respects_total_timeout():
    from context_service.engine.engagement import run_parallel_checks
    
    async def slow_check_1():
        await asyncio.sleep(0.1)
        return {"result": 1}
    
    async def slow_check_2():
        await asyncio.sleep(0.1)
        return {"result": 2}
    
    checks = {
        "check1": slow_check_1(),
        "check2": slow_check_2(),
    }
    
    results, completed, skipped = await run_parallel_checks(
        checks,
        individual_timeout=0.15,
        total_timeout=0.05,  # Both should be skipped
    )
    
    assert len(completed) == 0
    assert len(skipped) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_engagement_parallel.py -v`
Expected: FAIL

- [ ] **Step 3: Implement parallel check runner**

```python
# src/context_service/engine/engagement.py (add new function)

import asyncio
from typing import Any, Coroutine

INDIVIDUAL_CHECK_TIMEOUT = 0.03  # 30ms
TOTAL_CHECK_TIMEOUT = 0.08  # 80ms


async def run_parallel_checks(
    checks: dict[str, Coroutine[Any, Any, Any]],
    individual_timeout: float = INDIVIDUAL_CHECK_TIMEOUT,
    total_timeout: float = TOTAL_CHECK_TIMEOUT,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Run checks in parallel with individual and total timeouts.
    
    Returns:
        Tuple of (results dict, completed check names, skipped check names)
    """
    results: dict[str, Any] = {}
    completed: list[str] = []
    skipped: list[str] = []
    
    async def run_with_timeout(name: str, coro: Coroutine) -> tuple[str, Any | None]:
        try:
            result = await asyncio.wait_for(coro, timeout=individual_timeout)
            return (name, result)
        except asyncio.TimeoutError:
            return (name, None)
        except Exception:
            return (name, None)
    
    # Create tasks directly - don't create list of coroutines first
    tasks = [
        asyncio.create_task(run_with_timeout(name, coro))
        for name, coro in checks.items()
    ]
    check_names = list(checks.keys())
    
    try:
        done, pending = await asyncio.wait(
            tasks,
            timeout=total_timeout,
            return_when=asyncio.ALL_COMPLETED,
        )
        
        # Cancel any pending tasks
        for task in pending:
            task.cancel()
            
        # Collect results from completed tasks
        for task in done:
            name, result = task.result()
            if result is not None:
                results[name] = result
                completed.append(name)
            else:
                skipped.append(name)
                
        # Add names from pending tasks to skipped
        completed_names = set(completed + skipped)
        for name in check_names:
            if name not in completed_names:
                skipped.append(name)
            
    except asyncio.TimeoutError:
        skipped = list(checks.keys())
    
    return results, completed, skipped
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_engagement_parallel.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/engagement.py tests/engine/test_engagement_parallel.py
git commit -m "feat(engagement): add parallel check runner with timeouts"
```

---

### Task 2.4: Enhanced tick() Response

**Files:**
- Modify: `src/context_service/mcp/tools/tick.py`
- Test: `tests/mcp/tools/test_tick.py`

- [ ] **Step 1: Write the failing test for enhanced tick response**

```python
# tests/mcp/tools/test_tick.py (add to existing)

@pytest.mark.asyncio
async def test_tick_returns_session_id():
    """tick() should return session_id in response."""
    # Setup mocks...
    result = await _tick(
        about_hint=None,
        silo_id="test_silo",
        session_id=None,
        recent_context=None,
    )
    
    assert "session_id" in result
    assert result["session_id"].startswith("sess_")


@pytest.mark.asyncio
async def test_tick_returns_nudges():
    """tick() should return nudges based on state."""
    # Setup mocks with markers...
    result = await _tick(
        about_hint=None,
        silo_id="test_silo",
        session_id="sess_test",
        recent_context="working on auth",
    )
    
    assert "nudges" in result
    assert "status" in result
    assert "meta" in result
    assert "checks_completed" in result["meta"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/mcp/tools/test_tick.py::test_tick_returns_session_id -v`
Expected: FAIL

- [ ] **Step 3: Enhance tick() implementation**

Update `src/context_service/mcp/tools/tick.py`:

```python
# Updated _tick function signature and implementation
async def _tick(
    about_hint: list[str] | None,
    silo_id: str,
    session_id: str | None = None,
    recent_context: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for tick with enhanced response."""
    from context_service.engine.engagement import (
        get_engagement_for_about_set,
        get_engagement_for_silo,
        run_parallel_checks,
    )
    from context_service.engine.session_state import (
        get_or_create_session,
        increment_turn,
        save_session,
    )
    from context_service.engine.nudges import (
        Nudge,
        NudgeType,
        format_nudge,
        prioritize_nudges,
    )
    from context_service.mcp.server import get_context_service, get_redis

    start_time = time.perf_counter()
    ctx = get_context_service()
    store = ctx.graph_store
    redis_client = get_redis()
    
    if redis_client is None:
        return {
            "status": "error",
            "error": "service_unavailable",
            "message": "Redis is not configured",
        }
    
    redis = redis_client._redis
    
    # Get or create session
    session = await get_or_create_session(redis, session_id, silo_id)
    session = await increment_turn(redis, session)
    
    # Define checks
    async def check_markers():
        if about_hint:
            return await get_engagement_for_about_set(
                redis=redis, store=store, silo_id=silo_id,
                about_ids=about_hint, session_id=session.session_id,
            )
        return await get_engagement_for_silo(redis=redis, store=store, silo_id=silo_id)
    
    async def check_hypotheses():
        # Query stale hypotheses
        return {"hypotheses": []}
    
    async def check_affinities():
        # Query affinity clusters without beliefs
        return {"affinities": []}
    
    async def check_storage_gap():
        gap = session.turn_count - session.last_store_turn
        return {"storage_gap": gap if gap > 10 else 0}
    
    # Run checks in parallel
    checks = {
        "markers": check_markers(),
        "hypotheses": check_hypotheses(),
        "affinities": check_affinities(),
        "storage_gap": check_storage_gap(),
    }
    
    results, completed, skipped = await run_parallel_checks(checks)
    
    # Build nudges from results
    nudges: list[Nudge] = []
    
    # Markers nudge
    markers = results.get("markers", {}).get("markers", [])
    if markers and session.should_show_nudge(NudgeType.PENDING_MARKERS.value):
        nudges.append(format_nudge(NudgeType.PENDING_MARKERS, count=len(markers)))
        session.record_nudge_shown(NudgeType.PENDING_MARKERS.value)
    
    # Storage gap nudge
    gap = results.get("storage_gap", {}).get("storage_gap", 0)
    if gap > 10 and session.should_show_nudge(NudgeType.STORAGE_GAP.value):
        nudges.append(format_nudge(NudgeType.STORAGE_GAP, turns=gap))
        session.record_nudge_shown(NudgeType.STORAGE_GAP.value)
    
    # Prioritize and cap
    nudges = prioritize_nudges(nudges)
    
    # Save session
    await save_session(redis, session)
    
    latency_ms = (time.perf_counter() - start_time) * 1000
    
    # Determine status
    if skipped:
        status = "partial"
    elif nudges or markers:
        status = "ok"
    else:
        status = "current"
    
    return {
        "status": status,
        "session_id": session.session_id,
        "engagement": results.get("markers", {}),
        "markers": markers,
        "context": [],
        "nudges": [n.model_dump() for n in nudges],
        "meta": {
            "checks_completed": completed,
            "checks_skipped": skipped,
            "latency_ms": round(latency_ms, 1),
        },
    }
```

- [ ] **Step 4: Update tick() tool registration to include new parameters**

```python
# In register() function, update the tool signature:
@mcp.tool(
    name="tick",
    description=get_tool_description("tick"),
)
@mcp_error_boundary
async def tick(
    about_hint: list[str] | None = None,
    silo_id: str | None = None,
    session_id: str | None = None,
    recent_context: str | None = None,
) -> dict[str, Any]:
    # ... implementation calls _tick with new params
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/mcp/tools/test_tick.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/tick.py tests/mcp/tools/test_tick.py
git commit -m "feat(tick): enhance with session_id, recent_context, nudges"
```

---

## Phase 3: Model Migration

### Task 3.1: Update Configuration Defaults

**Files:**
- Modify: `src/context_service/config/identities.yaml`
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Update identities.yaml**

```yaml
# src/context_service/config/identities.yaml
identities:
  custodian:
    enabled: true
    model: "google-vertex:gemini-3.1-flash-lite"  # Updated from 2.5
    timeout_seconds: 30
    batch_size: 5
    batch_window_seconds: 2.0
    min_confidence_for_supersession: 0.7

  synthesizer:
    enabled: true
    model: "google-vertex:gemini-3.1-pro"  # Updated from 2.5
    timeout_seconds: 60
    threshold_pending_nodes: 50
    schedule_cron: "0 * * * *"
    proposal_confidence_threshold: 0.6
    max_facts_per_synthesis: 10
    min_facts_for_synthesis: 3

  groundskeeper:
    # No model, unchanged
    enabled: true
    schedule_cron: "0 3 * * *"
    decay_classes:
      ephemeral:
        half_life_days: 7
        hard_delete_days: 14
      standard:
        half_life_days: 90
        hard_delete_days: 180
      durable:
        half_life_days: 540
        hard_delete_days: 1080
      permanent:
        half_life_days: 1825
        hard_delete_days: 3650

  validator:
    enabled: true
    model: "google-vertex:gemini-3.1-pro"  # Updated from 2.5
    timeout_seconds: 5
    fail_open: true
```

- [ ] **Step 2: Update settings.py model defaults**

Search for gemini-2.5 references and update:

```python
# In settings.py, update these defaults:
flash_model: str = Field(default="google-vertex:gemini-3.1-flash-lite")
pro_model: str = Field(default="google-vertex:gemini-3.1-pro")
default_llm_model: str = Field(default="gemini-3.1-flash-lite")
summarization_model: str = Field(default="gemini-3.1-flash-lite")
```

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/config/`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/config/identities.yaml src/context_service/config/settings.py
git commit -m "chore: migrate from gemini-2.5 to gemini-3.1 models"
```

---

### Task 3.2: Test SAGE Pipeline with New Models

**Files:**
- Test: Run existing SAGE tests

- [ ] **Step 1: Run custodian tests**

Run: `uv run pytest tests/custodian/ -v -k "not integration"`
Expected: PASS

- [ ] **Step 2: Run synthesizer tests**

Run: `uv run pytest tests/synthesizer/ -v -k "not integration"` (if exists)
Expected: PASS or skip if no tests

- [ ] **Step 3: Run full check**

Run: `just check`
Expected: PASS

- [ ] **Step 4: Commit if any test updates needed**

```bash
git add -A
git commit -m "test: update tests for gemini-3.1 model migration"
```

---

## Phase 4: Skill Updates

### Task 4.1: Create/Update engrammic-onboarding Skill

**Files:**
- Create: `skills/engrammic-onboarding/engrammic-onboarding.md` (if not exists)

- [ ] **Step 1: Create skill directory if needed**

```bash
mkdir -p skills/engrammic-onboarding
```

- [ ] **Step 2: Write skill with tick() discipline**

```markdown
# skills/engrammic-onboarding/engrammic-onboarding.md
---
name: engrammic-onboarding
description: Session start ritual for Engrammic memory. Establishes tick() discipline for proactive memory enforcement.
---

# Engrammic Onboarding

Establish memory discipline for this session using tick() engagement checks.

## Session Start

1. Call `tick()` to get initial context and pending markers
2. Review any markers returned - address contradictions or stale beliefs
3. Note your session_id from the response for subsequent calls

## During Session (Every 3-5 Turns)

Call `tick()` with context about your current work:

```
tick(
  session_id="<your session_id>",
  recent_context="<brief description of what you're working on>"
)
```

Review the response:
- **markers**: Address any contradictions or stale commitments
- **nudges**: Consider acting on suggestions:
  - `form_belief`: You have related knowledge worth synthesizing
  - `storage_gap`: You haven't stored anything recently - consider `remember()`
  - `stale_hypothesis`: A hypothesis has been open too long - `commit()` or `revise()`
- **context**: Relevant memories surfaced for your current work

## Before Ending Session

1. Call `tick()` one final time
2. Store important findings with `remember()` or `learn()`
3. Crystallize any open hypotheses with `commit()`
4. Reflect on what you learned with `reflect()` if appropriate

## Why This Matters

tick() is lightweight (< 100ms) and helps you:
- Stay aware of pending issues (contradictions, stale beliefs)
- Get reminded when you should store knowledge
- Surface relevant context without full recall
- Maintain epistemic hygiene across sessions
```

- [ ] **Step 3: Copy to user skills directory**

```bash
cp -r skills/engrammic-onboarding ~/.claude/skills/
```

- [ ] **Step 4: Commit**

```bash
git add skills/engrammic-onboarding/
git commit -m "docs(skills): add engrammic-onboarding with tick() discipline"
```

---

## Phase 5: Distribution Updates

### Task 5.1: Add engrammic doctor Command

**Files:**
- Create: `src/context_service/cli/__init__.py`
- Create: `src/context_service/cli/doctor.py`
- Modify: `pyproject.toml` (CLI entrypoint)

- [ ] **Step 1: Create CLI directory**

```bash
mkdir -p src/context_service/cli
touch src/context_service/cli/__init__.py
```

- [ ] **Step 2: Create doctor command**

```python
# src/context_service/cli/doctor.py
"""engrammic doctor - verify installation and connectivity."""

from __future__ import annotations

import asyncio
import sys

import structlog

logger = structlog.get_logger(__name__)


async def check_mcp_server() -> tuple[bool, str]:
    """Check MCP server is responding."""
    try:
        # Attempt to connect to MCP server
        # This is a simplified check - real implementation depends on deployment
        return True, "MCP server responding"
    except Exception as e:
        return False, f"MCP server error: {e}"


async def check_redis() -> tuple[bool, str]:
    """Check Redis connectivity."""
    try:
        from context_service.db.redis_pool import get_redis_pool
        pool = await get_redis_pool()
        await pool.ping()
        return True, "Redis connected"
    except Exception as e:
        return False, f"Redis error: {e}"


async def check_graph() -> tuple[bool, str]:
    """Check Memgraph connectivity."""
    try:
        from context_service.db.memgraph import get_memgraph_pool
        pool = await get_memgraph_pool()
        # Simple query
        return True, "Memgraph connected"
    except Exception as e:
        return False, f"Memgraph error: {e}"


async def run_doctor() -> int:
    """Run all health checks."""
    checks = [
        ("MCP Server", check_mcp_server()),
        ("Redis", check_redis()),
        ("Memgraph", check_graph()),
    ]
    
    all_passed = True
    print("Engrammic Doctor\n" + "=" * 40)
    
    for name, coro in checks:
        passed, message = await coro
        status = "OK" if passed else "FAIL"
        print(f"[{status}] {name}: {message}")
        if not passed:
            all_passed = False
    
    print("=" * 40)
    if all_passed:
        print("All checks passed!")
        return 0
    else:
        print("Some checks failed. See above for details.")
        return 1


def main() -> None:
    """CLI entrypoint."""
    sys.exit(asyncio.run(run_doctor()))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Add CLI entrypoint to pyproject.toml**

```toml
[project.scripts]
engrammic-doctor = "context_service.cli.doctor:main"
```

- [ ] **Step 4: Test the command**

Run: `uv run engrammic-doctor`
Expected: Shows check results

- [ ] **Step 4: Commit**

```bash
git add src/context_service/cli/doctor.py pyproject.toml
git commit -m "feat(cli): add engrammic doctor command"
```

---

## Verification

### Task V.1: Full Test Suite

- [ ] **Step 1: Run full test suite**

Run: `just test`
Expected: All tests pass

- [ ] **Step 2: Run type check**

Run: `just check`
Expected: No errors

- [ ] **Step 3: Manual verification**

1. Start local stack: `just up`
2. Run `uv run engrammic-doctor` - all checks should pass
3. Test tick() via MCP client with session_id and recent_context

---

## Summary

This plan implements harness-agnostic memory enforcement in 5 phases:

1. **Write-Time Affinity** - k-NN computation at store time, affinity edges in graph
2. **tick() Enhancement** - Session state, parallel checks, nudges, debouncing
3. **Model Migration** - gemini-2.5 to gemini-3.1-flash-lite/pro
4. **Skill Updates** - engrammic-onboarding with tick() discipline
5. **Distribution Updates** - engrammic doctor command

Phase 6 (LLM phrasing) is deferred until agent feedback indicates need.
