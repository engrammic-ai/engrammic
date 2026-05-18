# Epistemic Layer Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three architectural issues: evidence accessibility stub, missing EpistemicStore abstraction, and orphan chain recovery.

**Architecture:** Three independent fixes in evidence-first order. Evidence fix uses ACCESSED_BY edges for session tracking. EpistemicStore wraps HyperGraphStore with domain methods. Orphan recovery uses Dagster scheduled job with exponential backoff.

**Tech Stack:** Python 3.13, FastAPI, Memgraph (Cypher), Postgres (SQLAlchemy), Dagster, structlog, pytest

---

## File Structure

### Issue 1: Evidence Accessibility
- Modify: `src/context_service/engine/queries.py` - add 4 new queries
- Modify: `src/context_service/engine/chain_applicability.py:134-144` - implement `get_accessible_evidence()`
- Modify: `src/context_service/mcp/tools/recall.py` - add access tracking
- Create: `tests/engine/test_evidence_accessibility.py`

### Issue 2: EpistemicStore Abstraction
- Modify: `src/context_service/engine/protocols.py` - add EpistemicStore protocol
- Create: `src/context_service/engine/epistemic_store.py` - MemgraphEpistemicStore implementation
- Modify: `src/context_service/engine/queries.py` - add EPISTEMIC_* queries
- Modify: `src/context_service/config/settings.py` - add feature flag
- Create: `tests/engine/test_epistemic_store.py`

### Issue 3: Orphan Chain Recovery
- Modify: `src/context_service/models/postgres/reasoning.py` - add `last_retry_at` column
- Create: `alembic/versions/xxx_add_orphan_last_retry_at.py` - migration
- Modify: `src/context_service/telemetry/metrics.py` - add counters
- Create: `src/context_service/pipelines/jobs/orphan_recovery.py` - Dagster job
- Modify: `src/context_service/pipelines/jobs/__init__.py` - export job
- Create: `tests/pipelines/test_orphan_recovery.py`

---

## Task 1: Add Evidence Accessibility Queries

**Files:**
- Modify: `src/context_service/engine/queries.py`

- [ ] **Step 1: Add evidence accessibility queries to queries.py**

Open `src/context_service/engine/queries.py` and add at the end of the file:

```python
# ---------------------------------------------------------------------------
# Evidence Accessibility (chain_applicability Layer 3)
# ---------------------------------------------------------------------------

GET_SESSION_ACCESSIBLE_EVIDENCE = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.session_id = $session_id 
   OR (n)<-[:ACCESSED_BY]-(:Session {id: $session_id})
RETURN n.id AS node_id
"""

MARK_NODE_ACCESSED = """
MATCH (n:Node {id: $node_id, silo_id: $silo_id})
MATCH (s:Session {id: $session_id, silo_id: $silo_id})
MERGE (n)<-[:ACCESSED_BY {at: timestamp()}]-(s)
"""

ENSURE_SESSION_NODE = """
MERGE (s:Session {id: $session_id, silo_id: $silo_id})
ON CREATE SET s.created_at = timestamp()
"""

GET_SILO_EVIDENCE_NODES = """
MATCH (n:Node {silo_id: $silo_id})
WHERE n.layer IN ['knowledge', 'memory']
RETURN n.id AS node_id
LIMIT $limit
"""
```

- [ ] **Step 2: Verify file syntax**

Run: `python -m py_compile src/context_service/engine/queries.py`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/engine/queries.py
git commit -m "feat(queries): add evidence accessibility queries for Layer 3"
```

---

## Task 2: Write Evidence Accessibility Tests

**Files:**
- Create: `tests/engine/test_evidence_accessibility.py`

- [ ] **Step 1: Create test file with failing tests**

```python
# tests/engine/test_evidence_accessibility.py
"""Tests for evidence accessibility in chain applicability Layer 3."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def mock_store():
    """Mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_query = AsyncMock()
    return store


@pytest.fixture
def mock_context_service(mock_store):
    """Mock context service with memgraph store."""
    ctx = MagicMock()
    ctx._memgraph = mock_store
    return ctx


class TestGetAccessibleEvidence:
    """Tests for get_accessible_evidence function."""

    @pytest.mark.asyncio
    async def test_returns_session_nodes(self, mock_store, mock_context_service):
        """Should return node IDs from session query."""
        mock_store.execute_query.return_value = [
            {"node_id": "node-1"},
            {"node_id": "node-2"},
        ]
        
        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence
            
            result = await get_accessible_evidence("silo-123", "session-456")
            
            assert result == {"node-1", "node-2"}
            mock_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_result(self, mock_store, mock_context_service):
        """Should fallback to silo-wide when session returns empty."""
        # First call returns empty (session), second returns silo-wide
        mock_store.execute_query.side_effect = [
            [],  # session query
            [{"node_id": "fallback-1"}],  # silo-wide fallback
        ]
        
        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence
            
            result = await get_accessible_evidence("silo-123", "session-456")
            
            assert result == {"fallback-1"}
            assert mock_store.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self, mock_store, mock_context_service):
        """Should fallback to silo-wide on query exception."""
        mock_store.execute_query.side_effect = [
            Exception("Connection failed"),
            [{"node_id": "fallback-1"}],
        ]
        
        with patch(
            "context_service.engine.chain_applicability.get_context_service",
            return_value=mock_context_service,
        ):
            from context_service.engine.chain_applicability import get_accessible_evidence
            
            result = await get_accessible_evidence("silo-123", "session-456")
            
            assert result == {"fallback-1"}


class TestGetSiloWideEvidence:
    """Tests for _get_silo_wide_evidence fallback."""

    @pytest.mark.asyncio
    async def test_returns_silo_nodes(self, mock_store):
        """Should return all evidence nodes in silo."""
        mock_store.execute_query.return_value = [
            {"node_id": "node-a"},
            {"node_id": "node-b"},
            {"node_id": "node-c"},
        ]
        
        from context_service.engine.chain_applicability import _get_silo_wide_evidence
        
        result = await _get_silo_wide_evidence("silo-123", mock_store)
        
        assert result == {"node-a", "node-b", "node-c"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_evidence_accessibility.py -v`
Expected: FAIL (functions not implemented yet)

- [ ] **Step 3: Commit test file**

```bash
git add tests/engine/test_evidence_accessibility.py
git commit -m "test(evidence): add failing tests for evidence accessibility"
```

---

## Task 3: Implement Evidence Accessibility

**Files:**
- Modify: `src/context_service/engine/chain_applicability.py:134-144`

- [ ] **Step 1: Replace the stub implementation**

In `src/context_service/engine/chain_applicability.py`, find the function `get_accessible_evidence` (around line 134) and replace it with:

```python
async def get_accessible_evidence(silo_id: str, session_id: str) -> set[str]:
    """Return evidence node IDs accessible within this session context.

    Queries nodes that were:
    1. Created by this session (agent authored, via session_id property)
    2. Retrieved/accessed during this session (tracked via ACCESSED_BY edge)

    Session ID availability: passed from MCP auth context through find_applicable_chain.
    """
    from context_service.engine import queries
    from context_service.mcp.server import get_context_service

    ctx = get_context_service()
    store = ctx._memgraph

    try:
        rows = await store.execute_query(
            queries.GET_SESSION_ACCESSIBLE_EVIDENCE,
            {"silo_id": silo_id, "session_id": session_id},
        )
        accessible = {str(r["node_id"]) for r in rows}

        # Fallback: if session tracking incomplete, be permissive
        # Better to reuse too many chains than penalize evidence use
        if not accessible:
            log.info(
                "session_evidence_empty_fallback",
                silo_id=silo_id,
                session_id=session_id,
            )
            return await _get_silo_wide_evidence(silo_id, store)
        return accessible
    except Exception as e:
        log.warning("accessible_evidence_query_failed", error=str(e))
        # On failure, permissive fallback
        return await _get_silo_wide_evidence(silo_id, store)


async def _get_silo_wide_evidence(silo_id: str, store) -> set[str]:
    """Fallback: return all evidence in silo (permissive)."""
    from context_service.engine import queries

    rows = await store.execute_query(
        queries.GET_SILO_EVIDENCE_NODES,
        {"silo_id": silo_id, "limit": 1000},
    )
    return {str(r["node_id"]) for r in rows}
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_evidence_accessibility.py -v`
Expected: PASS

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/engine/chain_applicability.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/chain_applicability.py
git commit -m "feat(evidence): implement session-scoped evidence accessibility"
```

---

## Task 4: Add Access Tracking to Recall Tool

**Files:**
- Modify: `src/context_service/mcp/tools/recall.py`

- [ ] **Step 1: Add access tracking after retrieval**

In `src/context_service/mcp/tools/recall.py`, find the `_recall_impl` function. After the `_context_recall` call (around line 45-50), add access tracking. The modified section should look like:

```python
async def _recall_impl(
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int | None = None,
    include_hypotheses: bool = False,
) -> dict[str, Any]:
    """Implementation for recall tool."""
    auth = await get_mcp_auth_context()
    silo_id = str(derive_silo_id(auth.org_id))
    session_id = auth.session_id

    effective_top_k = top_k
    if effective_top_k is None:
        effective_top_k = 10
        try:
            preset = await get_preset_resolver().resolve(silo_id)
            override = preset.param_overrides.get("default_recall_top_k")
            if (
                isinstance(override, int)
                and not isinstance(override, bool)
                and override > 0
            ):
                effective_top_k = override
        except RuntimeError:
            pass

    result = await _context_recall(
        silo_id=silo_id,
        query=query,
        node_ids=node_ids,
        depth=depth,
        layers=layers,
        top_k=effective_top_k,
    )

    # Track node access for evidence accessibility (Layer 3 chain reuse)
    if session_id and result.get("results"):
        await _track_node_access(silo_id, session_id, result["results"])

    if include_hypotheses:
        # ... rest of existing code
```

- [ ] **Step 2: Add the tracking helper function**

Add this function at the end of the file (before `register` function):

```python
async def _track_node_access(
    silo_id: str, session_id: str, results: list[dict[str, Any]]
) -> None:
    """Track that nodes were accessed by this session for evidence accessibility."""
    from context_service.engine import queries
    from context_service.mcp.server import get_context_service

    import structlog

    log = structlog.get_logger(__name__)

    try:
        ctx = get_context_service()
        store = ctx._memgraph

        # Ensure session node exists (idempotent)
        await store.execute_write(
            queries.ENSURE_SESSION_NODE,
            {"session_id": session_id, "silo_id": silo_id},
        )

        # Mark each retrieved node as accessed
        for item in results:
            node_id = item.get("node_id")
            if not node_id:
                continue
            try:
                await store.execute_write(
                    queries.MARK_NODE_ACCESSED,
                    {"node_id": node_id, "silo_id": silo_id, "session_id": session_id},
                )
            except Exception as e:
                # Non-fatal: log and continue
                log.warning("mark_node_accessed_failed", node_id=node_id, error=str(e))
    except Exception as e:
        # Non-fatal: don't break recall on tracking failure
        log.warning("track_node_access_failed", error=str(e))
```

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile src/context_service/mcp/tools/recall.py`
Expected: No output (success)

- [ ] **Step 4: Run type check**

Run: `uv run mypy src/context_service/mcp/tools/recall.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/recall.py
git commit -m "feat(recall): track node access for evidence accessibility"
```

---

## Task 5: Add Feature Flag for EpistemicStore

**Files:**
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Find the FeatureFlags class or create one**

Check if `FeatureFlags` exists:
Run: `grep -n "class FeatureFlags" src/context_service/config/settings.py`

If it doesn't exist, add it. Find the `Settings` class and add:

```python
class FeatureFlags(BaseModel):
    """Feature flags for gradual rollout."""

    use_epistemic_store: bool = Field(
        default=False,
        description="Use EpistemicStore abstraction for synthesis operations",
    )
```

Then add to the `Settings` class:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    
    feature_flags: FeatureFlags = Field(default_factory=FeatureFlags)
```

- [ ] **Step 2: Verify settings load**

Run: `uv run python -c "from context_service.config.settings import get_settings; s = get_settings(); print(s.feature_flags.use_epistemic_store)"`
Expected: `False`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/config/settings.py
git commit -m "feat(config): add use_epistemic_store feature flag"
```

---

## Task 6: Add EpistemicStore Protocol

**Files:**
- Modify: `src/context_service/engine/protocols.py`

- [ ] **Step 1: Add EpistemicStore protocol at end of file**

```python
@runtime_checkable
class EpistemicStore(Protocol):
    """CITE-domain operations for Wisdom/Intelligence layers.

    Sits above HyperGraphStore. Encapsulates belief synthesis,
    fact clustering, and reasoning chain operations.
    """

    async def get_fact_cluster(
        self, silo_id: str, cluster_id: str
    ) -> list[dict[str, Any]]:
        """Get all facts in a cluster."""
        ...

    async def get_unclustered_facts(
        self, silo_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get facts not yet assigned to any cluster."""
        ...

    async def create_belief_with_links(
        self,
        silo_id: str,
        content: str,
        fact_ids: list[str],
        confidence: float,
        reasoning: str | None = None,
    ) -> str:
        """Atomically create a belief and link it to source facts."""
        ...

    async def update_belief_centroid(
        self,
        silo_id: str,
        belief_id: str,
        embedding_client: Any | None = None,
    ) -> None:
        """Update belief's centroid embedding. No-op if embedding_client is None."""
        ...

    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]:
        """Find beliefs similar to the given content."""
        ...

    async def check_belief_coverage(
        self, silo_id: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        """Check which facts are covered by existing beliefs."""
        ...

    async def merge_beliefs(
        self,
        silo_id: str,
        source_belief_ids: list[str],
        merged_content: str,
        fact_ids: list[str],
    ) -> str:
        """Atomically merge beliefs: create merged, link facts, mark sources stale."""
        ...

    async def mark_belief_stale(
        self, silo_id: str, belief_id: str, reason: str
    ) -> None:
        """Mark a belief as stale with a reason."""
        ...
```

- [ ] **Step 2: Verify syntax and types**

Run: `uv run mypy src/context_service/engine/protocols.py`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/engine/protocols.py
git commit -m "feat(protocols): add EpistemicStore protocol for CITE-domain ops"
```

---

## Task 7: Add EpistemicStore Queries

**Files:**
- Modify: `src/context_service/engine/queries.py`

- [ ] **Step 1: Add EPISTEMIC_* queries at end of file**

```python
# ---------------------------------------------------------------------------
# EpistemicStore queries (belief synthesis domain operations)
# ---------------------------------------------------------------------------

EPISTEMIC_GET_FACT_CLUSTER = """
MATCH (f:Fact {silo_id: $silo_id})-[:IN_CLUSTER]->(c:Cluster {id: $cluster_id})
RETURN f.id AS id, f.content AS content, f.confidence AS confidence
"""

EPISTEMIC_GET_UNCLUSTERED_FACTS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE NOT (f)-[:IN_CLUSTER]->()
RETURN f.id AS id, f.content AS content, f.confidence AS confidence
LIMIT $limit
"""

EPISTEMIC_CREATE_BELIEF = """
CREATE (b:Belief:Node {
    id: randomUUID(),
    silo_id: $silo_id,
    content: $content,
    confidence: $confidence,
    reasoning: $reasoning,
    created_at: timestamp(),
    committed: false
})
RETURN b.id AS id
"""

EPISTEMIC_LINK_BELIEF_TO_FACTS = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
UNWIND $fact_ids AS fact_id
MATCH (f:Fact {id: fact_id, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
"""

EPISTEMIC_GET_BELIEF = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
RETURN b.content AS content, b.confidence AS confidence
"""

EPISTEMIC_UPDATE_BELIEF_CENTROID = """
MATCH (b:Belief {id: $belief_id})
SET b.centroid = $centroid
"""

EPISTEMIC_FIND_SIMILAR_BELIEFS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.committed = true
RETURN b.id AS id, b.content AS content, b.confidence AS confidence
"""

EPISTEMIC_CHECK_BELIEF_COVERAGE = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.id IN $fact_ids
OPTIONAL MATCH (f)<-[:SYNTHESIZED_FROM]-(b:Belief {committed: true})
RETURN f.id AS fact_id, collect(b.id) AS covering_beliefs
"""

EPISTEMIC_CREATE_MERGED_BELIEF = """
CREATE (b:Belief:Node {
    id: randomUUID(),
    silo_id: $silo_id,
    content: $content,
    created_at: timestamp(),
    committed: false,
    is_merged: true
})
RETURN b.id AS id
"""

EPISTEMIC_LINK_MERGED_FROM_SOURCES = """
MATCH (merged:Belief {id: $merged_id})
UNWIND $source_ids AS source_id
MATCH (source:Belief {id: source_id})
CREATE (merged)-[:MERGED_FROM]->(source)
"""

EPISTEMIC_MARK_BELIEF_STALE = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.stale = true, b.stale_reason = $reason, b.stale_at = timestamp()
"""
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile src/context_service/engine/queries.py`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/engine/queries.py
git commit -m "feat(queries): add EPISTEMIC_* queries for belief synthesis"
```

---

## Task 8: Write EpistemicStore Tests

**Files:**
- Create: `tests/engine/test_epistemic_store.py`

- [ ] **Step 1: Create test file**

```python
# tests/engine/test_epistemic_store.py
"""Tests for MemgraphEpistemicStore."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_graph_store():
    """Mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_query = AsyncMock()
    store.execute_write = AsyncMock()
    
    # Mock transaction context manager
    tx = AsyncMock()
    tx.execute_write = AsyncMock()
    tx.__aenter__ = AsyncMock(return_value=tx)
    tx.__aexit__ = AsyncMock(return_value=None)
    store.transaction = MagicMock(return_value=tx)
    
    return store


class TestMemgraphEpistemicStore:
    """Tests for MemgraphEpistemicStore implementation."""

    @pytest.mark.asyncio
    async def test_get_fact_cluster(self, mock_graph_store):
        """Should query facts in cluster."""
        mock_graph_store.execute_query.return_value = [
            {"id": "fact-1", "content": "fact content", "confidence": 0.9},
        ]
        
        from context_service.engine.epistemic_store import MemgraphEpistemicStore
        
        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.get_fact_cluster("silo-1", "cluster-1")
        
        assert len(result) == 1
        assert result[0]["id"] == "fact-1"
        mock_graph_store.execute_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_unclustered_facts(self, mock_graph_store):
        """Should query unclustered facts with limit."""
        mock_graph_store.execute_query.return_value = [
            {"id": "fact-1", "content": "content", "confidence": 0.8},
        ]
        
        from context_service.engine.epistemic_store import MemgraphEpistemicStore
        
        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.get_unclustered_facts("silo-1", limit=50)
        
        assert len(result) == 1
        call_args = mock_graph_store.execute_query.call_args
        assert call_args[0][1]["limit"] == 50

    @pytest.mark.asyncio
    async def test_create_belief_with_links_atomic(self, mock_graph_store):
        """Should create belief and links in transaction."""
        tx = mock_graph_store.transaction.return_value
        tx.__aenter__.return_value = tx
        tx.execute_write.return_value = [{"id": "belief-123"}]
        
        from context_service.engine.epistemic_store import MemgraphEpistemicStore
        
        store = MemgraphEpistemicStore(mock_graph_store)
        result = await store.create_belief_with_links(
            silo_id="silo-1",
            content="synthesized belief",
            fact_ids=["fact-1", "fact-2"],
            confidence=0.85,
        )
        
        assert result == "belief-123"
        # Should have called execute_write twice (create + link)
        assert tx.execute_write.call_count == 2

    @pytest.mark.asyncio
    async def test_update_belief_centroid_noop_without_client(self, mock_graph_store):
        """Should no-op when embedding_client is None."""
        from context_service.engine.epistemic_store import MemgraphEpistemicStore
        
        store = MemgraphEpistemicStore(mock_graph_store)
        await store.update_belief_centroid("silo-1", "belief-1", embedding_client=None)
        
        # Should not query anything
        mock_graph_store.execute_query.assert_not_called()
        mock_graph_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_mark_belief_stale(self, mock_graph_store):
        """Should mark belief as stale with reason."""
        from context_service.engine.epistemic_store import MemgraphEpistemicStore
        
        store = MemgraphEpistemicStore(mock_graph_store)
        await store.mark_belief_stale("silo-1", "belief-1", "merged_into:belief-2")
        
        mock_graph_store.execute_write.assert_called_once()
        call_args = mock_graph_store.execute_write.call_args
        assert call_args[0][1]["reason"] == "merged_into:belief-2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_epistemic_store.py -v`
Expected: FAIL (module doesn't exist yet)

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_epistemic_store.py
git commit -m "test(epistemic): add failing tests for EpistemicStore"
```

---

## Task 9: Implement MemgraphEpistemicStore

**Files:**
- Create: `src/context_service/engine/epistemic_store.py`

- [ ] **Step 1: Create the implementation file**

```python
# src/context_service/engine/epistemic_store.py
"""MemgraphEpistemicStore - CITE-domain operations over HyperGraphStore."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from context_service.engine import queries

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

log = structlog.get_logger(__name__)


class MemgraphEpistemicStore:
    """EpistemicStore implementation backed by Memgraph via HyperGraphStore."""

    def __init__(self, graph_store: HyperGraphStore) -> None:
        self._store = graph_store

    async def get_fact_cluster(
        self, silo_id: str, cluster_id: str
    ) -> list[dict[str, Any]]:
        """Get all facts in a cluster."""
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_FACT_CLUSTER,
            {"silo_id": silo_id, "cluster_id": cluster_id},
        )

    async def get_unclustered_facts(
        self, silo_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get facts not yet assigned to any cluster."""
        return await self._store.execute_query(
            queries.EPISTEMIC_GET_UNCLUSTERED_FACTS,
            {"silo_id": silo_id, "limit": limit},
        )

    async def create_belief_with_links(
        self,
        silo_id: str,
        content: str,
        fact_ids: list[str],
        confidence: float,
        reasoning: str | None = None,
    ) -> str:
        """Atomically create a belief and link it to source facts."""
        async with self._store.transaction() as tx:
            # Create belief node
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_BELIEF,
                {
                    "silo_id": silo_id,
                    "content": content,
                    "confidence": confidence,
                    "reasoning": reasoning,
                },
            )
            belief_id = result[0]["id"]

            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": belief_id, "fact_ids": fact_ids, "silo_id": silo_id},
            )
            return str(belief_id)

    async def update_belief_centroid(
        self,
        silo_id: str,
        belief_id: str,
        embedding_client: Any | None = None,
    ) -> None:
        """Update belief's centroid embedding. No-op if embedding_client is None."""
        if embedding_client is None:
            return

        # Fetch belief content
        belief = await self._store.execute_query(
            queries.EPISTEMIC_GET_BELIEF,
            {"silo_id": silo_id, "belief_id": belief_id},
        )
        if not belief:
            log.warning("belief_not_found_for_centroid", belief_id=belief_id)
            return

        # Compute and store embedding
        embedding = await embedding_client.embed(belief[0]["content"])
        await self._store.execute_write(
            queries.EPISTEMIC_UPDATE_BELIEF_CENTROID,
            {"belief_id": belief_id, "centroid": embedding},
        )

    async def find_similar_beliefs(
        self, silo_id: str, content: str, threshold: float = 0.8
    ) -> list[dict[str, Any]]:
        """Find beliefs similar to the given content."""
        return await self._store.execute_query(
            queries.EPISTEMIC_FIND_SIMILAR_BELIEFS,
            {"silo_id": silo_id, "content": content, "threshold": threshold},
        )

    async def check_belief_coverage(
        self, silo_id: str, fact_ids: list[str]
    ) -> dict[str, Any]:
        """Check which facts are covered by existing beliefs."""
        rows = await self._store.execute_query(
            queries.EPISTEMIC_CHECK_BELIEF_COVERAGE,
            {"silo_id": silo_id, "fact_ids": fact_ids},
        )
        return {"coverage": rows}

    async def merge_beliefs(
        self,
        silo_id: str,
        source_belief_ids: list[str],
        merged_content: str,
        fact_ids: list[str],
    ) -> str:
        """Atomically merge beliefs: create merged, link facts, mark sources stale."""
        async with self._store.transaction() as tx:
            # Create merged belief
            result = await tx.execute_write(
                queries.EPISTEMIC_CREATE_MERGED_BELIEF,
                {"silo_id": silo_id, "content": merged_content},
            )
            merged_id = result[0]["id"]

            # Link to facts
            await tx.execute_write(
                queries.EPISTEMIC_LINK_BELIEF_TO_FACTS,
                {"belief_id": merged_id, "fact_ids": fact_ids, "silo_id": silo_id},
            )

            # Link to source beliefs
            await tx.execute_write(
                queries.EPISTEMIC_LINK_MERGED_FROM_SOURCES,
                {"merged_id": merged_id, "source_ids": source_belief_ids},
            )

            # Mark source beliefs as stale
            for source_id in source_belief_ids:
                await tx.execute_write(
                    queries.EPISTEMIC_MARK_BELIEF_STALE,
                    {
                        "belief_id": source_id,
                        "silo_id": silo_id,
                        "reason": f"merged_into:{merged_id}",
                    },
                )

            return str(merged_id)

    async def mark_belief_stale(
        self, silo_id: str, belief_id: str, reason: str
    ) -> None:
        """Mark a belief as stale with a reason."""
        await self._store.execute_write(
            queries.EPISTEMIC_MARK_BELIEF_STALE,
            {"silo_id": silo_id, "belief_id": belief_id, "reason": reason},
        )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_epistemic_store.py -v`
Expected: PASS

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/engine/epistemic_store.py`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/epistemic_store.py
git commit -m "feat(epistemic): implement MemgraphEpistemicStore"
```

---

## Task 10: Add Orphan Recovery Metrics

**Files:**
- Modify: `src/context_service/telemetry/metrics.py`

- [ ] **Step 1: Add orphan recovery counters**

Find the metrics file and add these counters (near other Counter definitions):

```python
ORPHAN_CHAINS_EXHAUSTED = Counter(
    "context_orphan_chains_exhausted_total",
    "Number of orphan chains that exhausted all retries",
    ["silo_id"],
)

ORPHAN_CHAINS_RECOVERED = Counter(
    "context_orphan_chains_recovered_total",
    "Number of orphan chains successfully recovered",
    ["silo_id"],
)
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "from context_service.telemetry.metrics import ORPHAN_CHAINS_EXHAUSTED, ORPHAN_CHAINS_RECOVERED; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/telemetry/metrics.py
git commit -m "feat(telemetry): add orphan chain recovery metrics"
```

---

## Task 11: Add OrphanedChains Migration

**Files:**
- Modify: `src/context_service/models/postgres/reasoning.py`
- Create: `alembic/versions/xxx_add_orphan_last_retry_at.py`

- [ ] **Step 1: Update model with last_retry_at**

In `src/context_service/models/postgres/reasoning.py`, update the `OrphanedChains` class:

```python
class OrphanedChains(Base):
    """Dead-letter table for reasoning chains that failed processing."""

    __tablename__ = "orphaned_chains"

    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    last_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 2: Generate migration**

Run: `uv run alembic revision --autogenerate -m "add orphan last_retry_at"`

- [ ] **Step 3: Verify migration file**

Check the generated migration has:
```python
def upgrade():
    op.add_column('orphaned_chains', 
        sa.Column('last_retry_at', sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column('orphaned_chains', 'last_retry_at')
```

- [ ] **Step 4: Run migration**

Run: `uv run alembic upgrade head`
Expected: Migration applied successfully

- [ ] **Step 5: Commit**

```bash
git add src/context_service/models/postgres/reasoning.py alembic/versions/
git commit -m "feat(db): add last_retry_at column to orphaned_chains"
```

---

## Task 12: Write Orphan Recovery Tests

**Files:**
- Create: `tests/pipelines/test_orphan_recovery.py`

- [ ] **Step 1: Create test file**

```python
# tests/pipelines/test_orphan_recovery.py
"""Tests for orphan chain recovery job."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


class TestBackoffElapsed:
    """Tests for backoff timing logic."""

    def test_first_retry_always_eligible(self):
        """First retry (last_retry_at=None) should always be eligible."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed
        
        assert backoff_elapsed(retry_count=0, last_retry_at=None) is True

    def test_backoff_not_elapsed(self):
        """Should return False when backoff period not elapsed."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed
        
        # retry_count=1 means wait 10 minutes (2^1 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=5)
        assert backoff_elapsed(retry_count=1, last_retry_at=last_retry) is False

    def test_backoff_elapsed(self):
        """Should return True when backoff period has elapsed."""
        from context_service.pipelines.jobs.orphan_recovery import backoff_elapsed
        
        # retry_count=1 means wait 10 minutes (2^1 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=15)
        assert backoff_elapsed(retry_count=1, last_retry_at=last_retry) is True

    def test_exponential_backoff(self):
        """Backoff should be exponential: 5, 10, 20, 40, 80 minutes."""
        from context_service.pipelines.jobs.orphan_recovery import (
            BASE_BACKOFF_MINUTES,
            backoff_elapsed,
        )
        
        # retry_count=3 means wait 40 minutes (2^3 * 5)
        last_retry = datetime.now(UTC) - timedelta(minutes=30)
        assert backoff_elapsed(retry_count=3, last_retry_at=last_retry) is False
        
        last_retry = datetime.now(UTC) - timedelta(minutes=45)
        assert backoff_elapsed(retry_count=3, last_retry_at=last_retry) is True


class TestFetchChainFromPostgres:
    """Tests for chain data fetching."""

    @pytest.mark.asyncio
    async def test_fetches_chain_steps(self):
        """Should fetch and format chain steps."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_step = MagicMock()
        mock_step.content = "step content"
        mock_step.step_index = 0
        mock_step.silo_id = uuid4()
        mock_result.scalars.return_value.all.return_value = [mock_step]
        mock_session.execute.return_value = mock_result
        
        with patch(
            "context_service.pipelines.jobs.orphan_recovery.get_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            from context_service.pipelines.jobs.orphan_recovery import (
                fetch_chain_from_postgres,
            )
            
            chain_id = uuid4()
            result = await fetch_chain_from_postgres(chain_id)
            
            assert result["chain_id"] == str(chain_id)
            assert result["step_count"] == 1
            assert result["steps"][0]["content"] == "step content"

    @pytest.mark.asyncio
    async def test_raises_on_no_steps(self):
        """Should raise ValueError when no steps found."""
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result
        
        with patch(
            "context_service.pipelines.jobs.orphan_recovery.get_session"
        ) as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session
            
            from context_service.pipelines.jobs.orphan_recovery import (
                fetch_chain_from_postgres,
            )
            
            with pytest.raises(ValueError, match="No steps found"):
                await fetch_chain_from_postgres(uuid4())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/pipelines/test_orphan_recovery.py -v`
Expected: FAIL (module doesn't exist yet)

- [ ] **Step 3: Commit**

```bash
git add tests/pipelines/test_orphan_recovery.py
git commit -m "test(orphan): add failing tests for orphan recovery job"
```

---

## Task 13: Implement Orphan Recovery Job

**Files:**
- Create: `src/context_service/pipelines/jobs/orphan_recovery.py`
- Modify: `src/context_service/pipelines/jobs/__init__.py`

- [ ] **Step 1: Create the job file**

```python
# src/context_service/pipelines/jobs/orphan_recovery.py
"""Orphan chain recovery Dagster job.

Recovers reasoning chains that failed to write to Memgraph. Uses exponential
backoff with max 5 retries before alerting.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from dagster import Out, Output, job, op, schedule
from sqlalchemy import delete, select, update

from context_service.models.postgres.reasoning import OrphanedChains, ReasoningChainSteps
from context_service.telemetry.metrics import (
    ORPHAN_CHAINS_EXHAUSTED,
    ORPHAN_CHAINS_RECOVERED,
)

log = structlog.get_logger(__name__)

MAX_RETRIES = 5
BASE_BACKOFF_MINUTES = 5


def backoff_elapsed(retry_count: int, last_retry_at: datetime | None) -> bool:
    """Check if enough time has passed for next retry."""
    if last_retry_at is None:
        return True
    wait_minutes = (2**retry_count) * BASE_BACKOFF_MINUTES
    return datetime.now(UTC) > last_retry_at + timedelta(minutes=wait_minutes)


async def fetch_chain_from_postgres(chain_id: UUID) -> dict:
    """Fetch full chain data from Postgres for Memgraph projection."""
    from context_service.db.postgres import get_session

    async with get_session() as session:
        result = await session.execute(
            select(ReasoningChainSteps).where(ReasoningChainSteps.chain_id == chain_id)
        )
        steps = result.scalars().all()
        if not steps:
            raise ValueError(f"No steps found for chain {chain_id}")

        return {
            "chain_id": str(chain_id),
            "silo_id": str(steps[0].silo_id),
            "steps": [{"content": s.content, "step_index": s.step_index} for s in steps],
            "step_count": len(steps),
        }


async def delete_orphan(orphan_id: UUID) -> None:
    """Delete recovered orphan from dead-letter table."""
    from context_service.db.postgres import get_session

    async with get_session() as session:
        await session.execute(
            delete(OrphanedChains).where(OrphanedChains.chain_id == orphan_id)
        )
        await session.commit()


async def increment_retry(orphan_id: UUID) -> None:
    """Increment retry count and update last_retry_at."""
    from context_service.db.postgres import get_session

    async with get_session() as session:
        await session.execute(
            update(OrphanedChains)
            .where(OrphanedChains.chain_id == orphan_id)
            .values(
                retry_count=OrphanedChains.retry_count + 1,
                last_retry_at=datetime.now(UTC),
            )
        )
        await session.commit()


@op(out={"eligible": Out(), "exhausted": Out()})
def fetch_orphaned_chains(context):
    """Fetch chains eligible for retry and those exhausted."""
    from context_service.db.postgres import get_session

    async def _fetch():
        async with get_session() as session:
            # Eligible for retry
            result = await session.execute(
                select(OrphanedChains).where(OrphanedChains.retry_count < MAX_RETRIES)
            )
            chains = result.scalars().all()
            eligible = [
                c for c in chains if backoff_elapsed(c.retry_count, c.last_retry_at)
            ]

            # Exhausted (for alerting)
            exhausted_result = await session.execute(
                select(OrphanedChains).where(OrphanedChains.retry_count >= MAX_RETRIES)
            )
            exhausted = exhausted_result.scalars().all()

            return eligible, exhausted

    eligible, exhausted = asyncio.run(_fetch())
    context.log.info(f"Found {len(eligible)} eligible orphans, {len(exhausted)} exhausted")
    yield Output(eligible, output_name="eligible")
    yield Output(exhausted, output_name="exhausted")


@op
def retry_chains_to_memgraph(context, eligible: list) -> dict:
    """Attempt to write chain projections to Memgraph."""
    results = {"success": 0, "failed": 0}

    async def _retry():
        from context_service.mcp.server import get_context_service

        ctx = get_context_service()
        store = ctx._memgraph

        for orphan in eligible:
            try:
                chain_data = await fetch_chain_from_postgres(orphan.chain_id)
                await store.upsert_reasoning_chain_projection(chain_data)
                await delete_orphan(orphan.chain_id)
                results["success"] += 1
                ORPHAN_CHAINS_RECOVERED.labels(silo_id=str(orphan.silo_id)).inc()
                log.info("orphan_chain_recovered", chain_id=str(orphan.chain_id))
            except Exception as e:
                await increment_retry(orphan.chain_id)
                results["failed"] += 1
                log.warning(
                    "orphan_chain_retry_failed",
                    chain_id=str(orphan.chain_id),
                    retry_count=orphan.retry_count + 1,
                    error=str(e),
                )
        return results

    return asyncio.run(_retry())


@op
def alert_exhausted_chains(context, exhausted: list):
    """Alert on chains that hit max retries."""
    if not exhausted:
        return

    log.error(
        "orphan_chains_exhausted",
        count=len(exhausted),
        chain_ids=[str(c.chain_id) for c in exhausted],
    )

    for orphan in exhausted:
        ORPHAN_CHAINS_EXHAUSTED.labels(silo_id=str(orphan.silo_id)).inc()


@job
def orphan_chain_recovery_job():
    """Recover orphaned reasoning chains."""
    eligible, exhausted = fetch_orphaned_chains()
    retry_chains_to_memgraph(eligible)
    alert_exhausted_chains(exhausted)


@schedule(
    job=orphan_chain_recovery_job,
    cron_schedule="0 * * * *",  # hourly
)
def orphan_recovery_schedule(context):
    """Hourly schedule for orphan recovery."""
    return {}
```

- [ ] **Step 2: Update __init__.py to export the job**

In `src/context_service/pipelines/jobs/__init__.py`, add:

```python
from context_service.pipelines.jobs.orphan_recovery import (
    orphan_chain_recovery_job,
    orphan_recovery_schedule,
)

__all__ = [
    # ... existing exports ...
    "orphan_chain_recovery_job",
    "orphan_recovery_schedule",
]
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/pipelines/test_orphan_recovery.py -v`
Expected: PASS

- [ ] **Step 4: Run type check**

Run: `uv run mypy src/context_service/pipelines/jobs/orphan_recovery.py`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/context_service/pipelines/jobs/
git commit -m "feat(dagster): implement orphan chain recovery job with exponential backoff"
```

---

## Task 14: Run Full Test Suite

**Files:** None (verification only)

- [ ] **Step 1: Run all new tests**

Run: `uv run pytest tests/engine/test_evidence_accessibility.py tests/engine/test_epistemic_store.py tests/pipelines/test_orphan_recovery.py -v`
Expected: All PASS

- [ ] **Step 2: Run type check on all new files**

Run: `uv run mypy src/context_service/engine/chain_applicability.py src/context_service/engine/epistemic_store.py src/context_service/pipelines/jobs/orphan_recovery.py`
Expected: No errors

- [ ] **Step 3: Run lint**

Run: `uv run ruff check src/context_service/engine/ src/context_service/pipelines/jobs/ src/context_service/mcp/tools/recall.py`
Expected: No errors (or fix any found)

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: All tests pass

- [ ] **Step 5: Final commit if any fixes**

```bash
git add -A
git commit -m "fix: address lint/type issues from full test run"
```

---

## Task 15: Create PR

**Files:** None

- [ ] **Step 1: Push branch**

```bash
git push -u origin phase-epistemic-layer-fixes
```

- [ ] **Step 2: Create PR**

```bash
gh pr create --title "feat: epistemic layer fixes (evidence, abstraction, recovery)" --body "$(cat <<'EOF'
## Summary

Three architectural fixes from EAG exploration:

1. **Evidence accessibility** - Fix inverted incentive where chains WITH evidence couldn't reuse. Now uses ACCESSED_BY edges to track session-scoped evidence.

2. **EpistemicStore abstraction** - New protocol layer between synthesis and HyperGraphStore. Decouples from Cypher dialect, enables future store swapping.

3. **Orphan chain recovery** - Dagster job with exponential backoff (5/10/20/40/80 min) to recover chains that failed Memgraph write.

## Test plan

- [ ] Evidence: Create chain with evidence, verify Layer 3 passes after recall
- [ ] EpistemicStore: Feature flag off by default, toggle in staging
- [ ] Orphan recovery: Verify job runs hourly, metrics emit

## Spec

See `context/plans/2026-05-17-epistemic-layer-fixes.md`
EOF
)"
```

Done!
