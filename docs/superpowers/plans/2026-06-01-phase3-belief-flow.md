# Phase 3: Belief Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement TX4 SYNTHESIZE, TX5 REVISE_BELIEF, TX8 COMMIT, and TX14 CRYSTALLIZE transactions in the sage layer.

**Architecture:** Extend `sage/transactions.py` with all 4 transactions following existing patterns (typed results, ReactionEvents, invariant enforcement). TX8/TX14 are pure graph operations; TX4/TX5 integrate with LLM synthesis.

**Tech Stack:** Python 3.12, Memgraph (Cypher), AsyncMock for LLM mocking, pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/sage/transactions.py` | Add SynthesisState, ClusterState enums; CommitResult, CrystallizeResult, SynthesizeResult, ReviseBeliefResult dataclasses; tx8_commit, tx14_crystallize, tx4_synthesize, tx5_revise_belief functions |
| `src/context_service/db/queries.py` | Add GET_CLUSTER_FOR_SYNTHESIS, CREATE_COMMITMENT_WITH_ABOUT, CREATE_CRYSTALLIZED_FROM_EDGE, RELEASE_CLUSTER_LOCK queries |
| `tests/sage/test_belief_flow.py` | New test file for TX4, TX5, TX8, TX14 tests |

---

## Task 1: Add New Enums and Constants

**Files:**
- Modify: `src/context_service/sage/transactions.py:70-73`

- [ ] **Step 1: Add SynthesisState and ClusterState enums after existing enums**

Open `src/context_service/sage/transactions.py` and add after line 72 (after `PROMOTION_THRESHOLD = 3`):

```python
SYNTHESIS_THRESHOLD = 3
SYNTHESIS_CONFIDENCE_THRESHOLD = 0.6
MAX_CLUSTER_SIZE = 1000
MAX_SYNTHESIS_RETRIES = 3


class SynthesisState(StrEnum):
    """Belief synthesis states per brain-transactions-overview.md Section 4."""

    FRESH = "FRESH"
    STALE = "STALE"
    INVALIDATED = "INVALIDATED"


class ClusterState(StrEnum):
    """Cluster states per brain-transactions-overview.md Section 4.5."""

    SPARSE = "SPARSE"
    READY = "READY"
    SYNTHESIZED = "SYNTHESIZED"
    STALE = "STALE"
```

- [ ] **Step 2: Verify no syntax errors**

Run: `python -c "from context_service.sage.transactions import SynthesisState, ClusterState; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add SynthesisState and ClusterState enums for Phase 3"
```

---

## Task 2: Add Result Dataclasses for TX8 and TX14

**Files:**
- Modify: `src/context_service/sage/transactions.py` (after LinkResult dataclass, ~line 165)

- [ ] **Step 1: Add CommitResult and CrystallizeResult dataclasses**

Add after the `LinkResult` dataclass:

```python
@dataclass
class CommitResult:
    """Result of TX8 COMMIT."""

    commitment_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float


@dataclass
class CrystallizeResult:
    """Result of TX14 CRYSTALLIZE."""

    commitment_id: uuid.UUID
    hypothesis_id: uuid.UUID
    silo_id: str
    created_at: datetime
    confidence: float
```

- [ ] **Step 2: Verify import works**

Run: `python -c "from context_service.sage.transactions import CommitResult, CrystallizeResult; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add CommitResult and CrystallizeResult dataclasses"
```

---

## Task 3: Add Cypher Queries for TX8 and TX14

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add VALIDATE_ABOUT_REFS query**

Add near other validation queries:

```python
VALIDATE_ABOUT_REFS = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
RETURN n.id AS id, n.properties.state AS state
"""
```

- [ ] **Step 2: Add CREATE_COMMITMENT_WITH_ABOUT query**

```python
CREATE_COMMITMENT_WITH_ABOUT = """
CREATE (c:Node:Commitment {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    properties: $props
})
WITH c
UNWIND $about_ids AS aid
MATCH (a {id: aid, silo_id: $silo_id})
CREATE (c)-[:ABOUT]->(a)
WITH c
MERGE (agent:Agent {id: $agent_id})
CREATE (c)-[:DECLARED_BY {created_at: $created_at}]->(agent)
RETURN c.id AS id
"""
```

- [ ] **Step 3: Add GET_HYPOTHESIS_FOR_CRYSTALLIZE query**

```python
GET_HYPOTHESIS_FOR_CRYSTALLIZE = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id, silo_id: $silo_id})
WHERE h.properties.session_id = $session_id
RETURN h.id AS id,
       h.content AS content,
       h.properties.confidence AS confidence,
       h.properties.crystallized AS crystallized,
       h.properties.state AS state
"""
```

- [ ] **Step 4: Add GET_HYPOTHESIS_ABOUT_REFS query**

```python
GET_HYPOTHESIS_ABOUT_REFS = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id, silo_id: $silo_id})-[:ABOUT]->(a)
RETURN a.id AS id, a.properties.state AS state
"""
```

- [ ] **Step 5: Add CREATE_CRYSTALLIZED_FROM_EDGE query**

```python
CREATE_CRYSTALLIZED_FROM_EDGE = """
MATCH (commitment {id: $commitment_id, silo_id: $silo_id})
MATCH (hypothesis {id: $hypothesis_id, silo_id: $silo_id})
SET hypothesis.properties.crystallized = true,
    hypothesis.properties.crystallized_into = $commitment_id
CREATE (commitment)-[:CRYSTALLIZED_FROM {created_at: $created_at}]->(hypothesis)
RETURN commitment.id AS id
"""
```

- [ ] **Step 6: Verify queries are valid Python**

Run: `python -c "from context_service.db import queries; print('OK')"`
Expected: `OK`

- [ ] **Step 7: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Cypher queries for TX8 COMMIT and TX14 CRYSTALLIZE"
```

---

## Task 4: Write Failing Tests for TX8 COMMIT

**Files:**
- Create: `tests/sage/test_belief_flow.py`

- [ ] **Step 1: Create test file with imports and fixtures**

```python
"""Tests for Phase 3 belief flow transactions (TX4, TX5, TX8, TX14)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    CommitResult,
    InvariantViolation,
    NodeState,
    tx8_commit,
)


@pytest.fixture
def mock_store() -> AsyncMock:
    """Create a mock HyperGraphStore."""
    store = AsyncMock()
    store.execute_write = AsyncMock(return_value=[{"id": str(uuid.uuid4())}])
    store.execute_query = AsyncMock(return_value=[])
    return store


def make_uuid() -> str:
    """Generate a valid UUID string for tests."""
    return str(uuid.uuid4())
```

- [ ] **Step 2: Add test for basic TX8 commit**

```python
class TestTx8Commit:
    """Tests for TX8 COMMIT."""

    @pytest.mark.asyncio
    async def test_creates_commitment_with_about_edges(self, mock_store: AsyncMock) -> None:
        """Test that TX8 creates a commitment with ABOUT edges."""
        about_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[
            {"id": about_ref, "state": "ACTIVE"}
        ])

        result, events = await tx8_commit(
            store=mock_store,
            content="I believe X based on evidence",
            about_refs=[about_ref],
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, CommitResult)
        assert result.silo_id == "test-silo"
        assert isinstance(result.commitment_id, uuid.UUID)
        assert isinstance(result.created_at, datetime)
        assert 0.0 <= result.confidence <= 1.0
```

- [ ] **Step 3: Add test for empty about_refs rejection**

```python
    @pytest.mark.asyncio
    async def test_rejects_empty_about_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects empty about_refs (INV: commitment must be about something)."""
        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief without references",
                about_refs=[],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "EMPTY_ABOUT_REFS"
```

- [ ] **Step 4: Add test for tombstoned refs rejection**

```python
    @pytest.mark.asyncio
    async def test_rejects_tombstoned_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects tombstoned about_refs."""
        tombstoned_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[
            {"id": tombstoned_ref, "state": "TOMBSTONED"}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief about tombstoned node",
                about_refs=[tombstoned_ref],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ABOUT_REF_TOMBSTONED"
```

- [ ] **Step 5: Add test for missing refs rejection**

```python
    @pytest.mark.asyncio
    async def test_rejects_missing_refs(self, mock_store: AsyncMock) -> None:
        """Test that TX8 rejects about_refs that don't exist."""
        missing_ref = make_uuid()
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx8_commit(
                store=mock_store,
                content="Belief about missing node",
                about_refs=[missing_ref],
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ABOUT_REF_NOT_FOUND"
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_belief_flow.py -v`
Expected: All tests FAIL with `ImportError` (tx8_commit not defined yet)

- [ ] **Step 7: Commit failing tests**

```bash
git add tests/sage/test_belief_flow.py
git commit -m "test(sage): add failing tests for TX8 COMMIT"
```

---

## Task 5: Implement TX8 COMMIT

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add _validate_about_refs helper function**

Add after the existing `_validate_link` function:

```python
async def _validate_about_refs(
    store: HyperGraphStore,
    about_refs: list[str],
    silo_id: str,
) -> dict[str, Any]:
    """Validate about_refs exist, are in same silo, and not tombstoned."""
    from context_service.db import queries as q

    if not about_refs:
        return {"error": "EMPTY_ABOUT_REFS", "message": "about_refs must be non-empty"}

    results = await store.execute_query(q.VALIDATE_ABOUT_REFS, {
        "node_ids": about_refs,
        "silo_id": silo_id,
    })

    found_ids = {r["id"] for r in results}
    missing = set(about_refs) - found_ids
    if missing:
        return {
            "error": "ABOUT_REF_NOT_FOUND",
            "message": f"About refs not found: {missing}",
            "missing_ids": list(missing),
        }

    tombstoned = [r for r in results if r.get("state") == NodeState.TOMBSTONED.value]
    if tombstoned:
        return {
            "error": "ABOUT_REF_TOMBSTONED",
            "message": f"About refs are tombstoned: {[r['id'] for r in tombstoned]}",
        }

    return {"error": None}
```

- [ ] **Step 2: Implement tx8_commit function**

Add after the helper:

```python
async def tx8_commit(
    store: HyperGraphStore,
    content: str,
    about_refs: list[str],
    silo_id: str,
    agent_id: str,
    *,
    confidence: float = 0.8,
    metadata: dict[str, Any] | None = None,
) -> tuple[CommitResult, list[ReactionEvent]]:
    """TX8 COMMIT: Agent declares a stance directly.

    Per brain-transactions-pseudocode.md:
    - Enforces: about_refs non-empty, all exist in same silo (INV5), not tombstoned
    - Creates: Commitment node, ABOUT edges, DECLARED_BY edge (INV7)

    Args:
        store: Graph store instance.
        content: The commitment statement.
        about_refs: Node IDs this commitment is about (must be non-empty).
        silo_id: Tenant isolation ID.
        agent_id: Agent making the commitment.
        confidence: Confidence score 0.0-1.0.
        metadata: Additional properties.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        InvariantViolation: If preconditions not met.
    """
    from context_service.db import queries as q

    validation = await _validate_about_refs(store, about_refs, silo_id)
    if validation["error"]:
        raise InvariantViolation(
            validation["error"],
            validation["message"],
            **{k: v for k, v in validation.items() if k not in ("error", "message")},
        )

    commitment_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    props: dict[str, Any] = {
        "layer": "wisdom",
        "type": "commitment",
        "state": NodeState.ACTIVE.value,
        "confidence": confidence,
        "created_by": agent_id,
        **(metadata or {}),
    }

    await store.execute_write(
        q.CREATE_COMMITMENT_WITH_ABOUT,
        {
            "id": str(commitment_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "props": props,
            "about_ids": about_refs,
            "agent_id": agent_id,
        },
    )

    result = CommitResult(
        commitment_id=commitment_id,
        silo_id=silo_id,
        created_at=created_at,
        confidence=confidence,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="compute_embedding",
            node_id=str(commitment_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    logger.debug(
        "tx8_commit_complete",
        commitment_id=str(commitment_id),
        silo_id=silo_id,
        about_count=len(about_refs),
    )

    return result, events
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx8Commit -v`
Expected: All 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX8 COMMIT transaction"
```

---

## Task 6: Write Failing Tests for TX14 CRYSTALLIZE

**Files:**
- Modify: `tests/sage/test_belief_flow.py`

- [ ] **Step 1: Add imports for TX14**

Add to imports at top of file:

```python
from context_service.sage.transactions import (
    BrainError,
    CommitResult,
    CrystallizeResult,
    InvariantViolation,
    NodeState,
    tx8_commit,
    tx14_crystallize,
)
```

- [ ] **Step 2: Add test class for TX14**

```python
class TestTx14Crystallize:
    """Tests for TX14 CRYSTALLIZE."""

    @pytest.mark.asyncio
    async def test_converts_hypothesis_to_commitment(self, mock_store: AsyncMock) -> None:
        """Test that TX14 converts a WorkingHypothesis to a Commitment."""
        hypothesis_id = make_uuid()
        about_ref = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_HYPOTHESIS_FOR_CRYSTALLIZE
            [{"id": hypothesis_id, "content": "My hypothesis", "confidence": 0.9,
              "crystallized": False, "state": "ACTIVE"}],
            # GET_HYPOTHESIS_ABOUT_REFS
            [{"id": about_ref, "state": "ACTIVE"}],
        ])

        result, events = await tx14_crystallize(
            store=mock_store,
            hypothesis_id=hypothesis_id,
            silo_id="test-silo",
            agent_id="test-agent",
            session_id="test-session",
        )

        assert isinstance(result, CrystallizeResult)
        assert result.hypothesis_id == uuid.UUID(hypothesis_id)
        assert result.silo_id == "test-silo"
        assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_rejects_already_crystallized(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects already crystallized hypotheses."""
        hypothesis_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": hypothesis_id, "content": "Already done", "confidence": 0.9,
             "crystallized": True, "state": "ACTIVE"}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=hypothesis_id,
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "ALREADY_CRYSTALLIZED"

    @pytest.mark.asyncio
    async def test_rejects_missing_hypothesis(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects non-existent hypotheses."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=make_uuid(),
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "HYPOTHESIS_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_rejects_tombstoned_hypothesis(self, mock_store: AsyncMock) -> None:
        """Test that TX14 rejects tombstoned hypotheses."""
        hypothesis_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": hypothesis_id, "content": "Deleted", "confidence": 0.9,
             "crystallized": False, "state": "TOMBSTONED"}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx14_crystallize(
                store=mock_store,
                hypothesis_id=hypothesis_id,
                silo_id="test-silo",
                agent_id="test-agent",
                session_id="test-session",
            )

        assert exc_info.value.code == "HYPOTHESIS_TOMBSTONED"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx14Crystallize -v`
Expected: All tests FAIL with `ImportError` (tx14_crystallize not defined yet)

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_belief_flow.py
git commit -m "test(sage): add failing tests for TX14 CRYSTALLIZE"
```

---

## Task 7: Implement TX14 CRYSTALLIZE

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add _validate_hypothesis helper function**

```python
async def _validate_hypothesis(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    session_id: str,
) -> dict[str, Any]:
    """Validate hypothesis exists, belongs to session, not crystallized, not tombstoned."""
    from context_service.db import queries as q

    results = await store.execute_query(q.GET_HYPOTHESIS_FOR_CRYSTALLIZE, {
        "hypothesis_id": hypothesis_id,
        "silo_id": silo_id,
        "session_id": session_id,
    })

    if not results:
        return {"error": "HYPOTHESIS_NOT_FOUND", "message": "Hypothesis not found or wrong session"}

    row = results[0]
    if row.get("state") == NodeState.TOMBSTONED.value:
        return {"error": "HYPOTHESIS_TOMBSTONED", "message": "Hypothesis is tombstoned"}

    if row.get("crystallized"):
        return {
            "error": "ALREADY_CRYSTALLIZED",
            "message": "Hypothesis already crystallized",
        }

    return {
        "error": None,
        "content": row.get("content"),
        "confidence": row.get("confidence", 0.8),
    }
```

- [ ] **Step 2: Implement tx14_crystallize function**

```python
async def tx14_crystallize(
    store: HyperGraphStore,
    hypothesis_id: str,
    silo_id: str,
    agent_id: str,
    session_id: str,
) -> tuple[CrystallizeResult, list[ReactionEvent]]:
    """TX14 CRYSTALLIZE: Convert WorkingHypothesis to Commitment.

    Per brain-transactions-pseudocode.md:
    - Preconditions: hypothesis exists, belongs to session, not crystallized, not tombstoned
    - Creates: Commitment copying content/confidence, ABOUT edges, DECLARED_BY, CRYSTALLIZED_FROM
    - Updates: hypothesis.crystallized = true, hypothesis.crystallized_into = commitment_id

    Args:
        store: Graph store instance.
        hypothesis_id: ID of the WorkingHypothesis to crystallize.
        silo_id: Tenant isolation ID.
        agent_id: Agent performing crystallization.
        session_id: Session the hypothesis belongs to.

    Returns:
        Tuple of (result, reaction_events).

    Raises:
        InvariantViolation: If preconditions not met.
    """
    from context_service.db import queries as q

    validation = await _validate_hypothesis(store, hypothesis_id, silo_id, session_id)
    if validation["error"]:
        raise InvariantViolation(
            validation["error"],
            validation["message"],
        )

    content = validation["content"]
    confidence = float(validation["confidence"])

    # Get about_refs from hypothesis
    about_results = await store.execute_query(q.GET_HYPOTHESIS_ABOUT_REFS, {
        "hypothesis_id": hypothesis_id,
        "silo_id": silo_id,
    })

    about_refs = [r["id"] for r in about_results]
    tombstoned = [r for r in about_results if r.get("state") == NodeState.TOMBSTONED.value]
    if tombstoned:
        raise InvariantViolation(
            "ABOUT_REF_TOMBSTONED",
            f"About refs are tombstoned: {[r['id'] for r in tombstoned]}",
        )

    commitment_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    props: dict[str, Any] = {
        "layer": "wisdom",
        "type": "commitment",
        "state": NodeState.ACTIVE.value,
        "confidence": confidence,
        "created_by": agent_id,
        "source_hypothesis_id": hypothesis_id,
    }

    # Create commitment with ABOUT edges and DECLARED_BY
    await store.execute_write(
        q.CREATE_COMMITMENT_WITH_ABOUT,
        {
            "id": str(commitment_id),
            "silo_id": silo_id,
            "content": content,
            "created_at": created_at.isoformat(),
            "props": props,
            "about_ids": about_refs,
            "agent_id": agent_id,
        },
    )

    # Create CRYSTALLIZED_FROM edge and update hypothesis
    await store.execute_write(
        q.CREATE_CRYSTALLIZED_FROM_EDGE,
        {
            "commitment_id": str(commitment_id),
            "hypothesis_id": hypothesis_id,
            "silo_id": silo_id,
            "created_at": created_at.isoformat(),
        },
    )

    result = CrystallizeResult(
        commitment_id=commitment_id,
        hypothesis_id=uuid.UUID(hypothesis_id),
        silo_id=silo_id,
        created_at=created_at,
        confidence=confidence,
    )

    events: list[ReactionEvent] = [
        ReactionEvent(
            event_type="compute_embedding",
            node_id=str(commitment_id),
            silo_id=silo_id,
        ),
        ReactionEvent(
            event_type="update_heat",
            node_id=str(commitment_id),
            silo_id=silo_id,
            payload={"access_type": "WRITE"},
        ),
    ]

    logger.debug(
        "tx14_crystallize_complete",
        commitment_id=str(commitment_id),
        hypothesis_id=hypothesis_id,
        silo_id=silo_id,
    )

    return result, events
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx14Crystallize -v`
Expected: All 4 tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX14 CRYSTALLIZE transaction"
```

---

## Task 8: Add Result Dataclasses for TX4 and TX5

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add SynthesizeResult and ReviseBeliefResult dataclasses**

Add after CrystallizeResult:

```python
@dataclass
class SynthesizeResult:
    """Result of TX4 SYNTHESIZE."""

    belief_id: uuid.UUID | None
    cluster_id: str
    cluster_state: ClusterState
    fact_count: int
    confidence: float | None
    timed_out: bool = False


@dataclass
class ReviseBeliefResult:
    """Result of TX5 REVISE_BELIEF."""

    new_belief_id: uuid.UUID | None
    old_belief_id: uuid.UUID
    content_changed: bool
    invalidated: bool = False


@dataclass
class LLMSynthesisResult:
    """Result from LLM synthesis call."""

    success: bool
    content: str | None
    caveats: list[str]
    timed_out: bool
    error: str | None = None
```

- [ ] **Step 2: Verify imports work**

Run: `python -c "from context_service.sage.transactions import SynthesizeResult, ReviseBeliefResult, LLMSynthesisResult; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add SynthesizeResult, ReviseBeliefResult, LLMSynthesisResult dataclasses"
```

---

## Task 9: Add Cypher Queries for TX4 and TX5

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add GET_CLUSTER_FOR_SYNTHESIS query**

```python
GET_CLUSTER_FOR_SYNTHESIS = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
SET c.synthesis_in_progress = true
RETURN c.state AS state,
       c.current_belief_id AS current_belief_id,
       c.synthesis_retry_count AS synthesis_retry_count
"""
```

- [ ] **Step 2: Add RELEASE_CLUSTER_LOCK query**

```python
RELEASE_CLUSTER_LOCK = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
SET c.synthesis_in_progress = false,
    c.state = $state
RETURN c.id AS id
"""
```

- [ ] **Step 3: Add UPDATE_CLUSTER_AFTER_SYNTHESIS query**

```python
UPDATE_CLUSTER_AFTER_SYNTHESIS = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
SET c.synthesis_in_progress = false,
    c.state = $state,
    c.current_belief_id = $belief_id,
    c.synthesized_at = $synthesized_at,
    c.synthesis_retry_count = 0
RETURN c.id AS id
"""
```

- [ ] **Step 4: Add CREATE_BELIEF_WITH_SYNTHESIZED_FROM query**

```python
CREATE_BELIEF_WITH_SYNTHESIZED_FROM = """
CREATE (b:Node:Belief {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    properties: $props
})
WITH b
UNWIND $fact_ids AS fid
MATCH (f {id: fid, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN b.id AS id
"""
```

- [ ] **Step 5: Add GET_BELIEF_FOR_REVISION query**

```python
GET_BELIEF_FOR_REVISION = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
RETURN b.id AS id,
       b.content AS content,
       b.properties.state AS state,
       b.properties.synthesis_state AS synthesis_state,
       b.properties.source_cluster_id AS source_cluster_id,
       b.properties.revision_in_progress AS revision_in_progress,
       b.properties.confidence AS confidence
"""
```

- [ ] **Step 6: Add MARK_BELIEF_REVISION_IN_PROGRESS query**

```python
MARK_BELIEF_REVISION_IN_PROGRESS = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.properties.revision_in_progress = true
RETURN b.id AS id
"""
```

- [ ] **Step 7: Add UPDATE_BELIEF_AFTER_REVISION query**

```python
UPDATE_BELIEF_AFTER_REVISION = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.properties.synthesis_state = $synthesis_state,
    b.properties.revision_in_progress = false
RETURN b.id AS id
"""
```

- [ ] **Step 8: Verify queries are valid Python**

Run: `python -c "from context_service.db import queries; print('OK')"`
Expected: `OK`

- [ ] **Step 9: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Cypher queries for TX4 SYNTHESIZE and TX5 REVISE_BELIEF"
```

---

## Task 10: Add Helper Functions for Synthesis

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add noisy_or_aggregate helper**

Add with other helpers:

```python
def noisy_or_aggregate(confidences: list[float]) -> float:
    """Compute noisy-or aggregation of confidence values.

    Formula: 1 - product(1 - c_i)
    Gives higher aggregate when multiple independent sources agree.
    """
    if not confidences:
        return 0.0
    product = 1.0
    for c in confidences:
        product *= (1.0 - max(0.0, min(1.0, c)))
    return 1.0 - product
```

- [ ] **Step 2: Add llm_synthesize helper**

```python
async def llm_synthesize(
    llm: Any,  # LLMProvider
    facts: list[dict[str, Any]],
    timeout: float,
    previous_belief: str | None = None,
) -> LLMSynthesisResult:
    """Call LLM to synthesize a belief from facts.

    Args:
        llm: LLM provider instance.
        facts: List of fact dicts with 'content' and 'confidence' keys.
        timeout: Timeout in seconds.
        previous_belief: For revisions, the previous belief content.

    Returns:
        LLMSynthesisResult with synthesis output or error.
    """
    import asyncio

    from context_service.engine.synthesis import _build_synthesis_prompt, _SYNTHESIS_SYSTEM_PROMPT

    prompt = _build_synthesis_prompt(facts)
    if previous_belief:
        prompt += f"\n\nPrevious belief (now stale): {previous_belief}"

    try:
        response = await asyncio.wait_for(
            llm.complete(
                system_prompt=_SYNTHESIS_SYSTEM_PROMPT,
                user_prompt=prompt,
            ),
            timeout=timeout,
        )
        return LLMSynthesisResult(
            success=True,
            content=response.strip(),
            caveats=[],
            timed_out=False,
        )
    except asyncio.TimeoutError:
        return LLMSynthesisResult(
            success=False,
            content=None,
            caveats=[],
            timed_out=True,
            error="synthesis timed out",
        )
    except Exception as e:
        return LLMSynthesisResult(
            success=False,
            content=None,
            caveats=[],
            timed_out=False,
            error=str(e),
        )
```

- [ ] **Step 3: Verify helpers import correctly**

Run: `python -c "from context_service.sage.transactions import noisy_or_aggregate; print(noisy_or_aggregate([0.8, 0.7]))"`
Expected: ~0.94 (should print a float)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add noisy_or_aggregate and llm_synthesize helpers"
```

---

## Task 11: Write Failing Tests for TX4 SYNTHESIZE

**Files:**
- Modify: `tests/sage/test_belief_flow.py`

- [ ] **Step 1: Update imports**

```python
from context_service.sage.transactions import (
    BrainError,
    ClusterState,
    CommitResult,
    CrystallizeResult,
    InvariantViolation,
    NodeState,
    SynthesizeResult,
    tx4_synthesize,
    tx8_commit,
    tx14_crystallize,
)
```

- [ ] **Step 2: Add mock LLM fixture**

```python
@pytest.fixture
def mock_llm() -> AsyncMock:
    """Create a mock LLM provider."""
    llm = AsyncMock()
    llm.complete = AsyncMock(return_value="Synthesized belief content")
    return llm


@pytest.fixture
def mock_embedder() -> AsyncMock:
    """Create a mock embedding service."""
    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[0.1] * 768)
    return embedder
```

- [ ] **Step 3: Add TX4 test class**

```python
class TestTx4Synthesize:
    """Tests for TX4 SYNTHESIZE."""

    @pytest.mark.asyncio
    async def test_creates_belief_from_cluster(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 creates a belief from a ready cluster."""
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert isinstance(result, SynthesizeResult)
        assert result.belief_id is not None
        assert result.cluster_state == ClusterState.SYNTHESIZED
        assert result.fact_count == 3
        assert not result.timed_out

    @pytest.mark.asyncio
    async def test_skips_sparse_cluster(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 skips clusters with fewer than SYNTHESIS_THRESHOLD facts."""
        cluster_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - only 2 facts
            [{"id": make_uuid(), "content": "Fact 1", "confidence": 0.8},
             {"id": make_uuid(), "content": "Fact 2", "confidence": 0.8}],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.belief_id is None
        assert result.cluster_state == ClusterState.SPARSE
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_low_confidence(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX4 skips when aggregate confidence is below threshold."""
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "READY", "current_belief_id": None, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - low confidence facts
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.2}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx4_synthesize(
            store=mock_store,
            cluster_id=cluster_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.belief_id is None
        assert result.confidence is not None
        assert result.confidence < 0.6
        mock_llm.complete.assert_not_called()
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx4Synthesize -v`
Expected: All tests FAIL with `ImportError` (tx4_synthesize not defined yet)

- [ ] **Step 5: Commit failing tests**

```bash
git add tests/sage/test_belief_flow.py
git commit -m "test(sage): add failing tests for TX4 SYNTHESIZE"
```

---

## Task 12: Implement TX4 SYNTHESIZE

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add TYPE_CHECKING imports for LLM types**

Update the TYPE_CHECKING block at top of file:

```python
if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.engine.protocols import HyperGraphStore
    from context_service.llm.base import LLMProvider
```

- [ ] **Step 2: Add Literal import**

Add to imports at top:

```python
from typing import TYPE_CHECKING, Any, Literal
```

- [ ] **Step 3: Implement tx4_synthesize function**

```python
async def tx4_synthesize(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
    *,
    mode: Literal["async", "sync"] = "async",
    timeout_seconds: float = 30.0,
) -> tuple[SynthesizeResult, list[ReactionEvent]]:
    """TX4 SYNTHESIZE: Create Belief from fact cluster.

    Per brain-transactions-pseudocode.md:
    - Modes: ASYNC (30s timeout), SYNC (2s timeout for query-time)
    - Enforces INV3: Every Belief has >= N SYNTHESIZED_FROM to ACTIVE Facts

    Args:
        store: Graph store instance.
        cluster_id: ID of the cluster to synthesize.
        silo_id: Tenant isolation ID.
        llm: LLM provider for synthesis.
        embedder: Embedding service.
        mode: "async" (background) or "sync" (query-time).
        timeout_seconds: LLM timeout (default 30s, use 2s for sync).

    Returns:
        Tuple of (result, reaction_events).
    """
    from context_service.db import queries as q

    effective_timeout = 2.0 if mode == "sync" else timeout_seconds

    # Acquire lock on cluster
    lock_result = await store.execute_query(q.GET_CLUSTER_FOR_SYNTHESIS, {
        "cluster_id": cluster_id,
        "silo_id": silo_id,
    })

    if not lock_result:
        return SynthesizeResult(
            belief_id=None,
            cluster_id=cluster_id,
            cluster_state=ClusterState.SPARSE,
            fact_count=0,
            confidence=None,
        ), []

    cluster_state = lock_result[0].get("state", "SPARSE")

    try:
        # Fetch facts in cluster
        facts_result = await store.execute_query(q.GET_FACTS_IN_CLUSTER, {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
        })

        facts = list(facts_result) if facts_result else []
        fact_count = len(facts)

        # Check threshold
        if fact_count < SYNTHESIS_THRESHOLD:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.SPARSE.value,
            })
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.SPARSE,
                fact_count=fact_count,
                confidence=None,
            ), []

        # Compute aggregate confidence
        confidences = [float(f.get("confidence", 0.8)) for f in facts]
        aggregate_confidence = noisy_or_aggregate(confidences)

        if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.READY.value,
            })
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.READY,
                fact_count=fact_count,
                confidence=aggregate_confidence,
            ), []

        # Call LLM
        synthesis_result = await llm_synthesize(llm, facts, effective_timeout)

        if synthesis_result.timed_out:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.READY.value,
            })
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.READY,
                fact_count=fact_count,
                confidence=aggregate_confidence,
                timed_out=True,
            ), []

        if not synthesis_result.success:
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.READY.value,
            })
            logger.warning("tx4_synthesize_failed", error=synthesis_result.error)
            return SynthesizeResult(
                belief_id=None,
                cluster_id=cluster_id,
                cluster_state=ClusterState.READY,
                fact_count=fact_count,
                confidence=aggregate_confidence,
            ), []

        # Create belief
        belief_id = uuid.uuid4()
        created_at = datetime.now(UTC)

        props: dict[str, Any] = {
            "layer": "wisdom",
            "type": "belief",
            "state": NodeState.ACTIVE.value,
            "synthesis_state": SynthesisState.FRESH.value,
            "confidence": aggregate_confidence,
            "source_cluster_id": cluster_id,
        }

        fact_ids = [f["id"] for f in facts]

        await store.execute_write(q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM, {
            "id": str(belief_id),
            "silo_id": silo_id,
            "content": synthesis_result.content,
            "created_at": created_at.isoformat(),
            "props": props,
            "fact_ids": fact_ids,
        })

        # Update cluster
        await store.execute_write(q.UPDATE_CLUSTER_AFTER_SYNTHESIS, {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
            "state": ClusterState.SYNTHESIZED.value,
            "belief_id": str(belief_id),
            "synthesized_at": created_at.isoformat(),
        })

        events: list[ReactionEvent] = [
            ReactionEvent(
                event_type="compute_embedding",
                node_id=str(belief_id),
                silo_id=silo_id,
            ),
            ReactionEvent(
                event_type="update_heat",
                node_id=str(belief_id),
                silo_id=silo_id,
                payload={"access_type": "SYNTHESIS"},
            ),
        ]

        logger.debug(
            "tx4_synthesize_complete",
            belief_id=str(belief_id),
            cluster_id=cluster_id,
            fact_count=fact_count,
        )

        return SynthesizeResult(
            belief_id=belief_id,
            cluster_id=cluster_id,
            cluster_state=ClusterState.SYNTHESIZED,
            fact_count=fact_count,
            confidence=aggregate_confidence,
        ), events

    except Exception as e:
        # Always release lock on error
        await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
            "state": cluster_state,
        })
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx4Synthesize -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX4 SYNTHESIZE transaction"
```

---

## Task 13: Write Failing Tests for TX5 REVISE_BELIEF

**Files:**
- Modify: `tests/sage/test_belief_flow.py`

- [ ] **Step 1: Update imports**

```python
from context_service.sage.transactions import (
    BrainError,
    ClusterState,
    CommitResult,
    CrystallizeResult,
    InvariantViolation,
    NodeState,
    ReviseBeliefResult,
    SynthesizeResult,
    tx4_synthesize,
    tx5_revise_belief,
    tx8_commit,
    tx14_crystallize,
)
```

- [ ] **Step 2: Add TX5 test class**

```python
class TestTx5ReviseBelief:
    """Tests for TX5 REVISE_BELIEF."""

    @pytest.mark.asyncio
    async def test_creates_new_belief_on_content_change(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 creates a new belief when content changes."""
        belief_id = make_uuid()
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_llm.complete = AsyncMock(return_value="New revised belief content")

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert isinstance(result, ReviseBeliefResult)
        assert result.new_belief_id is not None
        assert result.old_belief_id == uuid.UUID(belief_id)
        assert result.content_changed is True
        assert result.invalidated is False

    @pytest.mark.asyncio
    async def test_skips_unchanged_content(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 skips creating new belief if content unchanged."""
        belief_id = make_uuid()
        cluster_id = make_uuid()
        fact_ids = [make_uuid() for _ in range(3)]

        mock_llm.complete = AsyncMock(return_value="Old belief")  # Same content

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER
            [{"id": fid, "content": f"Fact {i}", "confidence": 0.8}
             for i, fid in enumerate(fact_ids)],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.new_belief_id is None
        assert result.content_changed is False

    @pytest.mark.asyncio
    async def test_invalidates_unsupported_belief(
        self, mock_store: AsyncMock, mock_llm: AsyncMock, mock_embedder: AsyncMock
    ) -> None:
        """Test that TX5 invalidates belief when facts drop below threshold."""
        belief_id = make_uuid()
        cluster_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_BELIEF_FOR_REVISION
            [{"id": belief_id, "content": "Old belief", "state": "ACTIVE",
              "synthesis_state": "STALE", "source_cluster_id": cluster_id,
              "revision_in_progress": False, "confidence": 0.8}],
            # GET_CLUSTER_FOR_SYNTHESIS
            [{"state": "STALE", "current_belief_id": belief_id, "synthesis_retry_count": 0}],
            # GET_FACTS_IN_CLUSTER - only 1 fact now
            [{"id": make_uuid(), "content": "Lonely fact", "confidence": 0.8}],
        ])

        result, events = await tx5_revise_belief(
            store=mock_store,
            belief_id=belief_id,
            silo_id="test-silo",
            llm=mock_llm,
            embedder=mock_embedder,
        )

        assert result.new_belief_id is None
        assert result.invalidated is True
        mock_llm.complete.assert_not_called()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx5ReviseBelief -v`
Expected: All tests FAIL with `ImportError` (tx5_revise_belief not defined yet)

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_belief_flow.py
git commit -m "test(sage): add failing tests for TX5 REVISE_BELIEF"
```

---

## Task 14: Implement TX5 REVISE_BELIEF

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement tx5_revise_belief function**

```python
async def tx5_revise_belief(
    store: HyperGraphStore,
    belief_id: str,
    silo_id: str,
    llm: LLMProvider,
    embedder: EmbeddingService,
) -> tuple[ReviseBeliefResult, list[ReactionEvent]]:
    """TX5 REVISE_BELIEF: Re-synthesize a stale belief.

    Per brain-transactions-pseudocode.md:
    - Preconditions: belief ACTIVE with synthesis_state=STALE, no revision in progress
    - Creates: new Belief if content changed, SUPERSEDES edge
    - Updates: old belief to SUPERSEDED, cluster.current_belief_id

    Args:
        store: Graph store instance.
        belief_id: ID of the stale belief to revise.
        silo_id: Tenant isolation ID.
        llm: LLM provider for synthesis.
        embedder: Embedding service.

    Returns:
        Tuple of (result, reaction_events).
    """
    from context_service.db import queries as q

    # Get belief and validate
    belief_result = await store.execute_query(q.GET_BELIEF_FOR_REVISION, {
        "belief_id": belief_id,
        "silo_id": silo_id,
    })

    if not belief_result:
        raise InvariantViolation("BELIEF_NOT_FOUND", "Belief not found")

    belief = belief_result[0]
    if belief.get("state") != NodeState.ACTIVE.value:
        raise InvariantViolation("BELIEF_NOT_ACTIVE", "Belief is not active")

    if belief.get("synthesis_state") != SynthesisState.STALE.value:
        raise InvariantViolation(
            "BELIEF_NOT_STALE",
            f"Belief synthesis_state is {belief.get('synthesis_state')}, not STALE",
        )

    if belief.get("revision_in_progress"):
        raise InvariantViolation("REVISION_IN_PROGRESS", "Revision already in progress")

    cluster_id = belief.get("source_cluster_id")
    old_content = belief.get("content", "")
    old_confidence = float(belief.get("confidence", 0.8))

    # Mark revision in progress
    await store.execute_write(q.MARK_BELIEF_REVISION_IN_PROGRESS, {
        "belief_id": belief_id,
        "silo_id": silo_id,
    })

    try:
        # Acquire cluster lock
        lock_result = await store.execute_query(q.GET_CLUSTER_FOR_SYNTHESIS, {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
        })

        try:
            # Fetch current facts
            facts_result = await store.execute_query(q.GET_FACTS_IN_CLUSTER, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
            })

            facts = list(facts_result) if facts_result else []
            fact_count = len(facts)

            # Check threshold - invalidate if below
            if fact_count < SYNTHESIS_THRESHOLD:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SPARSE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None,
                    old_belief_id=uuid.UUID(belief_id),
                    content_changed=False,
                    invalidated=True,
                ), []

            # Compute aggregate confidence
            confidences = [float(f.get("confidence", 0.8)) for f in facts]
            aggregate_confidence = noisy_or_aggregate(confidences)

            if aggregate_confidence < SYNTHESIS_CONFIDENCE_THRESHOLD:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.INVALIDATED.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SPARSE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None,
                    old_belief_id=uuid.UUID(belief_id),
                    content_changed=False,
                    invalidated=True,
                ), []

            # Call LLM with previous belief context
            synthesis_result = await llm_synthesize(llm, facts, 30.0, previous_belief=old_content)

            if not synthesis_result.success:
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.STALE.value,  # Keep stale for retry
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.STALE.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None,
                    old_belief_id=uuid.UUID(belief_id),
                    content_changed=False,
                ), []

            # Check if content changed
            new_content = synthesis_result.content or ""
            if new_content.strip() == old_content.strip():
                # No change - mark fresh
                await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                    "belief_id": belief_id,
                    "silo_id": silo_id,
                    "synthesis_state": SynthesisState.FRESH.value,
                })
                await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                    "cluster_id": cluster_id,
                    "silo_id": silo_id,
                    "state": ClusterState.SYNTHESIZED.value,
                })
                return ReviseBeliefResult(
                    new_belief_id=None,
                    old_belief_id=uuid.UUID(belief_id),
                    content_changed=False,
                ), []

            # Create new belief
            new_belief_id = uuid.uuid4()
            created_at = datetime.now(UTC)

            props: dict[str, Any] = {
                "layer": "wisdom",
                "type": "belief",
                "state": NodeState.ACTIVE.value,
                "synthesis_state": SynthesisState.FRESH.value,
                "confidence": aggregate_confidence,
                "source_cluster_id": cluster_id,
            }

            fact_ids = [f["id"] for f in facts]

            await store.execute_write(q.CREATE_BELIEF_WITH_SYNTHESIZED_FROM, {
                "id": str(new_belief_id),
                "silo_id": silo_id,
                "content": new_content,
                "created_at": created_at.isoformat(),
                "props": props,
                "fact_ids": fact_ids,
            })

            # Supersede old belief
            await _create_supersedes_edge(
                store, str(new_belief_id), belief_id, silo_id, SupersedeReason.EVIDENCE_SHIFT
            )

            # Clear revision flag on old belief (it's now superseded anyway)
            await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
                "belief_id": belief_id,
                "silo_id": silo_id,
                "synthesis_state": SynthesisState.FRESH.value,  # Doesn't matter, it's superseded
            })

            # Update cluster
            await store.execute_write(q.UPDATE_CLUSTER_AFTER_SYNTHESIS, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.SYNTHESIZED.value,
                "belief_id": str(new_belief_id),
                "synthesized_at": created_at.isoformat(),
            })

            events: list[ReactionEvent] = [
                ReactionEvent(
                    event_type="compute_embedding",
                    node_id=str(new_belief_id),
                    silo_id=silo_id,
                ),
                ReactionEvent(
                    event_type="update_heat",
                    node_id=str(new_belief_id),
                    silo_id=silo_id,
                    payload={"access_type": "SYNTHESIS"},
                ),
            ]

            logger.debug(
                "tx5_revise_belief_complete",
                new_belief_id=str(new_belief_id),
                old_belief_id=belief_id,
            )

            return ReviseBeliefResult(
                new_belief_id=new_belief_id,
                old_belief_id=uuid.UUID(belief_id),
                content_changed=True,
            ), events

        except Exception:
            # Release cluster lock on error
            await store.execute_write(q.RELEASE_CLUSTER_LOCK, {
                "cluster_id": cluster_id,
                "silo_id": silo_id,
                "state": ClusterState.STALE.value,
            })
            raise

    except Exception:
        # Clear revision flag on error
        await store.execute_write(q.UPDATE_BELIEF_AFTER_REVISION, {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "synthesis_state": SynthesisState.STALE.value,
        })
        raise
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_belief_flow.py::TestTx5ReviseBelief -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX5 REVISE_BELIEF transaction"
```

---

## Task 15: Run Full Test Suite and Type Check

**Files:**
- All sage files

- [ ] **Step 1: Run all Phase 3 tests**

Run: `uv run pytest tests/sage/test_belief_flow.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing transaction tests**

Run: `uv run pytest tests/sage/test_transactions.py -v`
Expected: All existing tests still PASS (no regressions)

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/context_service/sage/transactions.py --strict`
Expected: No errors (or only pre-existing ones)

- [ ] **Step 4: Run linter**

Run: `uv run ruff check src/context_service/sage/`
Expected: No new errors

- [ ] **Step 5: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix(sage): address type and lint issues in Phase 3 transactions"
```

---

## Task 16: Update Module Exports

**Files:**
- Modify: `src/context_service/sage/__init__.py`

- [ ] **Step 1: Add new exports to __init__.py**

```python
"""Sage: Brain architecture transaction layer."""

from context_service.sage.confidence import compute_credibility
from context_service.sage.consolidation import (
    ConflictSignals,
    ConsolidationWorker,
    DeterministicResolver,
    ResolutionAction,
    ResolutionResult,
)
from context_service.sage.transactions import (
    BrainError,
    ClusterState,
    CommitResult,
    ConflictError,
    ConflictStatus,
    CrossSiloViolation,
    CrystallizeResult,
    CycleError,
    InvariantViolation,
    LinkResult,
    LinkType,
    NodeState,
    ReactionEvent,
    ReviseBeliefResult,
    StoreClaimResult,
    StoreMemoryResult,
    SupersedeReason,
    SupersedeResult,
    SynthesisState,
    SynthesizeResult,
    tx0_store_memory,
    tx2_store_claim,
    tx3_supersede,
    tx4_synthesize,
    tx5_revise_belief,
    tx8_commit,
    tx14_crystallize,
    tx17_link,
)

__all__ = [
    # Confidence
    "compute_credibility",
    # Consolidation
    "ConflictSignals",
    "ConsolidationWorker",
    "DeterministicResolver",
    "ResolutionAction",
    "ResolutionResult",
    # Transactions - Enums
    "ClusterState",
    "ConflictStatus",
    "LinkType",
    "NodeState",
    "SupersedeReason",
    "SynthesisState",
    # Transactions - Errors
    "BrainError",
    "ConflictError",
    "CrossSiloViolation",
    "CycleError",
    "InvariantViolation",
    # Transactions - Results
    "CommitResult",
    "CrystallizeResult",
    "LinkResult",
    "ReactionEvent",
    "ReviseBeliefResult",
    "StoreClaimResult",
    "StoreMemoryResult",
    "SupersedeResult",
    "SynthesizeResult",
    # Transactions - Functions
    "tx0_store_memory",
    "tx2_store_claim",
    "tx3_supersede",
    "tx4_synthesize",
    "tx5_revise_belief",
    "tx8_commit",
    "tx14_crystallize",
    "tx17_link",
]
```

- [ ] **Step 2: Verify imports work**

Run: `python -c "from context_service.sage import tx4_synthesize, tx5_revise_belief, tx8_commit, tx14_crystallize; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/__init__.py
git commit -m "feat(sage): export Phase 3 transactions from module"
```

---

## Task 17: Update Brain Architecture Plan

**Files:**
- Modify: `context/plans/2026-06-01-brain-architecture.md`

- [ ] **Step 1: Mark Phase 3 tasks complete**

Update the Phase 3 section:

```markdown
### Phase 3: Belief Flow

8. [x] TX4 SYNTHESIZE - cluster synthesis with lazy trigger
9. [x] TX5 REVISE_BELIEF - belief update with staleness cascade
10. [x] TX14 CRYSTALLIZE - WorkingHypothesis to Commitment
11. [x] TX8 COMMIT - session hypothesis promotion
```

- [ ] **Step 2: Update status**

Change the header status to:

```markdown
**Status:** Phase 3 complete, Phase 4 next
```

- [ ] **Step 3: Commit**

```bash
git add context/plans/2026-06-01-brain-architecture.md
git commit -m "docs: mark Phase 3 tasks complete in brain architecture plan"
```

---

## Summary

This plan implements 4 transactions across 17 tasks:

| Transaction | Tests | Implementation |
|-------------|-------|----------------|
| TX8 COMMIT | 4 tests | Task 4-5 |
| TX14 CRYSTALLIZE | 4 tests | Task 6-7 |
| TX4 SYNTHESIZE | 3 tests | Task 11-12 |
| TX5 REVISE_BELIEF | 3 tests | Task 13-14 |

Total: 14 new tests, ~400 lines of transaction code, ~100 lines of queries.
