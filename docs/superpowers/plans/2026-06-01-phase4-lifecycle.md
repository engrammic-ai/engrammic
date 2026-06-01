# Phase 4: Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement TX15 FORGET, TX16 CANCEL_FORGET, TX10 HARD_DELETE, and CASCADE_STALENESS helper in the sage layer.

**Architecture:** Extend `sage/transactions.py` with deletion lifecycle transactions. TX15/TX16 are synchronous operations; TX10 is batch GC; CASCADE_STALENESS is depth-limited propagation (sync depth-1, async deeper).

**Tech Stack:** Python 3.12, Memgraph (Cypher), AsyncMock for testing, pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/sage/transactions.py` | Add ForgetResult, CancelForgetResult, HardDeleteResult dataclasses; tx15_forget, tx16_cancel_forget, tx10_hard_delete, cascade_staleness functions |
| `src/context_service/db/queries.py` | Add TOMBSTONE_NODE, RESTORE_TOMBSTONED_NODE, GET_DEPENDENTS_FOR_CASCADE, HARD_DELETE_NODE, DELETE_EDGES_FOR_NODE queries |
| `tests/sage/test_lifecycle.py` | New test file for TX10, TX15, TX16, CASCADE_STALENESS tests |

---

## Task 1: Add Constants and Result Dataclasses

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Add lifecycle constants**

Add after existing constants:

```python
CANCEL_WINDOW_DURATION_SECONDS = 3600  # 60 minutes
MAX_CASCADE_DEPTH = 10
```

- [ ] **Step 2: Add ForgetResult, CancelForgetResult, HardDeleteResult dataclasses**

Add after existing dataclasses:

```python
@dataclass
class ForgetResult:
    """Result of TX15 FORGET."""

    node_id: uuid.UUID
    state: NodeState
    tombstoned_at: datetime
    cancel_window_expires: datetime
    cascade_count: int = 0


@dataclass
class CancelForgetResult:
    """Result of TX16 CANCEL_FORGET."""

    node_id: uuid.UUID
    restored_at: datetime
    previous_state: NodeState


@dataclass
class HardDeleteResult:
    """Result of TX10 HARD_DELETE."""

    deleted_count: int
    skipped_count: int
    deleted_ids: list[str]
```

- [ ] **Step 3: Verify imports work**

Run: `python -c "from context_service.sage.transactions import ForgetResult, CancelForgetResult, HardDeleteResult; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): add lifecycle result dataclasses for Phase 4"
```

---

## Task 2: Add Cypher Queries for Lifecycle

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add TOMBSTONE_NODE query**

```python
TOMBSTONE_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state IN ['ACTIVE', 'SUPERSEDED']
SET n.properties.state = 'TOMBSTONED',
    n.properties.tombstoned_at = $tombstoned_at,
    n.properties.forget_requested_at = $forget_requested_at,
    n.properties.forget_requested_by = $agent_id,
    n.properties.forget_reason = $reason,
    n.properties.cancel_window_expires = $cancel_window_expires,
    n.properties.previous_state = n.properties.state
RETURN n.id AS id, n.properties.state AS state
"""
```

- [ ] **Step 2: Add RESTORE_TOMBSTONED_NODE query**

```python
RESTORE_TOMBSTONED_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
  AND n.properties.cancel_window_expires > $now
SET n.properties.state = n.properties.previous_state,
    n.properties.tombstoned_at = null,
    n.properties.forget_requested_at = null,
    n.properties.forget_requested_by = null,
    n.properties.forget_reason = null,
    n.properties.cancel_window_expires = null,
    n.properties.restored_at = $restored_at,
    n.properties.restored_by = $agent_id
RETURN n.id AS id, n.properties.state AS state, n.properties.previous_state AS previous_state
"""
```

- [ ] **Step 3: Add GET_NODE_FOR_FORGET query**

```python
GET_NODE_FOR_FORGET = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.id AS id,
       n.properties.state AS state,
       n.properties.layer AS layer,
       n.properties.cancel_window_expires AS cancel_window_expires
"""
```

- [ ] **Step 4: Add GET_DEPENDENTS_FOR_CASCADE query**

```python
GET_DEPENDENTS_FOR_CASCADE = """
MATCH (d)-[e:SYNTHESIZED_FROM|DERIVED_FROM]->(changed {id: $node_id, silo_id: $silo_id})
WHERE d.properties.state = 'ACTIVE'
RETURN d.id AS id, d.properties.layer AS layer, type(e) AS edge_type
"""
```

- [ ] **Step 5: Add MARK_BELIEF_STALE query**

```python
MARK_BELIEF_STALE = """
MATCH (b {id: $node_id, silo_id: $silo_id})
WHERE b.properties.layer = 'wisdom'
SET b.properties.synthesis_state = 'STALE'
RETURN b.id AS id
"""
```

- [ ] **Step 6: Add GET_TOMBSTONED_FOR_GC query**

```python
GET_TOMBSTONED_FOR_GC = """
MATCH (n {silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
  AND n.properties.cancel_window_expires < $now
RETURN n.id AS id
LIMIT $batch_size
"""
```

- [ ] **Step 7: Add DELETE_EDGES_FOR_NODE query**

```python
DELETE_EDGES_FOR_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[e]-()
DELETE e
RETURN count(e) AS deleted_count
"""
```

- [ ] **Step 8: Add HARD_DELETE_NODE query**

```python
HARD_DELETE_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
DELETE n
RETURN count(n) AS deleted_count
"""
```

- [ ] **Step 9: Verify queries are valid Python**

Run: `python -c "from context_service.db import queries; print('OK')"`

- [ ] **Step 10: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Cypher queries for lifecycle transactions"
```

---

## Task 3: Write Failing Tests for TX15 FORGET

**Files:**
- Create: `tests/sage/test_lifecycle.py`

- [ ] **Step 1: Create test file with imports and fixtures**

```python
"""Tests for Phase 4 lifecycle transactions (TX10, TX15, TX16, CASCADE_STALENESS)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from context_service.sage.transactions import (
    BrainError,
    CancelForgetResult,
    ForgetResult,
    HardDeleteResult,
    InvariantViolation,
    NodeState,
    tx15_forget,
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

- [ ] **Step 2: Add TestTx15Forget class**

```python
class TestTx15Forget:
    """Tests for TX15 FORGET."""

    @pytest.mark.asyncio
    async def test_tombstones_active_node(self, mock_store: AsyncMock) -> None:
        """Test that TX15 tombstones an active node."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "layer": "memory", "cancel_window_expires": None}
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED"}
        ])

        result, events = await tx15_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, ForgetResult)
        assert result.state == NodeState.TOMBSTONED
        assert result.cancel_window_expires > datetime.now(UTC)

    @pytest.mark.asyncio
    async def test_rejects_already_tombstoned(self, mock_store: AsyncMock) -> None:
        """Test that TX15 rejects already tombstoned nodes."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "layer": "memory", "cancel_window_expires": None}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx15_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "ALREADY_TOMBSTONED"

    @pytest.mark.asyncio
    async def test_rejects_missing_node(self, mock_store: AsyncMock) -> None:
        """Test that TX15 rejects non-existent nodes."""
        mock_store.execute_query = AsyncMock(return_value=[])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx15_forget(
                store=mock_store,
                node_id=make_uuid(),
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NODE_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_cascades_to_dependents(self, mock_store: AsyncMock) -> None:
        """Test that TX15 with cascade=True triggers CASCADE_STALENESS."""
        node_id = make_uuid()
        dependent_id = make_uuid()

        mock_store.execute_query = AsyncMock(side_effect=[
            # GET_NODE_FOR_FORGET
            [{"id": node_id, "state": "ACTIVE", "layer": "knowledge", "cancel_window_expires": None}],
            # GET_DEPENDENTS_FOR_CASCADE
            [{"id": dependent_id, "layer": "wisdom", "edge_type": "SYNTHESIZED_FROM"}],
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED"}
        ])

        result, events = await tx15_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
            cascade=True,
        )

        assert result.cascade_count >= 1
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx15Forget -v`
Expected: All tests FAIL with `ImportError` (tx15_forget not defined yet)

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_lifecycle.py
git commit -m "test(sage): add failing tests for TX15 FORGET"
```

---

## Task 4: Implement TX15 FORGET

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement tx15_forget function**

```python
async def tx15_forget(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    agent_id: str,
    *,
    reason: str | None = None,
    cascade: bool = False,
) -> tuple[ForgetResult, list[ReactionEvent]]:
    """TX15 FORGET: Soft-delete a node with cancel window.

    Per brain-transactions-pseudocode.md:
    - Preconditions: node exists, state is ACTIVE or SUPERSEDED
    - Sets state to TOMBSTONED, records cancel_window_expires
    - Optional cascade triggers CASCADE_STALENESS on dependents
    """
    from context_service.db import queries as q

    # Validate node exists and is not already tombstoned
    node_result = await store.execute_query(q.GET_NODE_FOR_FORGET, {
        "node_id": node_id,
        "silo_id": silo_id,
    })

    if not node_result:
        raise InvariantViolation("NODE_NOT_FOUND", "Node not found")

    node = node_result[0]
    state = node.get("state")

    if state == NodeState.TOMBSTONED.value:
        raise InvariantViolation("ALREADY_TOMBSTONED", "Node is already tombstoned")

    if state == NodeState.DELETED.value:
        raise InvariantViolation("ALREADY_DELETED", "Node is already deleted")

    if state not in (NodeState.ACTIVE.value, NodeState.SUPERSEDED.value):
        raise InvariantViolation("INVALID_STATE", f"Cannot forget node in state {state}")

    now = datetime.now(UTC)
    cancel_window_expires = now + timedelta(seconds=CANCEL_WINDOW_DURATION_SECONDS)

    # Tombstone the node
    await store.execute_write(q.TOMBSTONE_NODE, {
        "node_id": node_id,
        "silo_id": silo_id,
        "tombstoned_at": now.isoformat(),
        "forget_requested_at": now.isoformat(),
        "agent_id": agent_id,
        "reason": reason,
        "cancel_window_expires": cancel_window_expires.isoformat(),
    })

    cascade_count = 0
    events: list[ReactionEvent] = []

    if cascade:
        # Trigger staleness cascade
        cascade_count = await cascade_staleness(store, node_id, silo_id, depth=1)
        events.append(ReactionEvent(
            event_type="cascade_staleness_complete",
            node_id=node_id,
            silo_id=silo_id,
            payload={"cascade_count": cascade_count},
        ))

    result = ForgetResult(
        node_id=uuid.UUID(node_id),
        state=NodeState.TOMBSTONED,
        tombstoned_at=now,
        cancel_window_expires=cancel_window_expires,
        cascade_count=cascade_count,
    )

    logger.debug("tx15_forget_complete", node_id=node_id, silo_id=silo_id, cascade_count=cascade_count)

    return result, events
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx15Forget -v`
Expected: All 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX15 FORGET transaction"
```

---

## Task 5: Write Failing Tests for TX16 CANCEL_FORGET

**Files:**
- Modify: `tests/sage/test_lifecycle.py`

- [ ] **Step 1: Add imports for TX16**

Add `tx16_cancel_forget` to imports.

- [ ] **Step 2: Add TestTx16CancelForget class**

```python
class TestTx16CancelForget:
    """Tests for TX16 CANCEL_FORGET."""

    @pytest.mark.asyncio
    async def test_restores_tombstoned_node(self, mock_store: AsyncMock) -> None:
        """Test that TX16 restores a tombstoned node within cancel window."""
        node_id = make_uuid()
        future_time = (datetime.now(UTC) + timedelta(hours=1)).isoformat()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "cancel_window_expires": future_time}
        ])
        mock_store.execute_write = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "previous_state": "ACTIVE"}
        ])

        result = await tx16_cancel_forget(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            agent_id="test-agent",
        )

        assert isinstance(result, CancelForgetResult)
        assert result.previous_state == NodeState.ACTIVE

    @pytest.mark.asyncio
    async def test_rejects_expired_window(self, mock_store: AsyncMock) -> None:
        """Test that TX16 rejects nodes past cancel window."""
        node_id = make_uuid()
        past_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "TOMBSTONED", "cancel_window_expires": past_time}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx16_cancel_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "CANCEL_WINDOW_EXPIRED"

    @pytest.mark.asyncio
    async def test_rejects_non_tombstoned(self, mock_store: AsyncMock) -> None:
        """Test that TX16 rejects non-tombstoned nodes."""
        node_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id, "state": "ACTIVE", "cancel_window_expires": None}
        ])

        with pytest.raises(InvariantViolation) as exc_info:
            await tx16_cancel_forget(
                store=mock_store,
                node_id=node_id,
                silo_id="test-silo",
                agent_id="test-agent",
            )

        assert exc_info.value.code == "NOT_TOMBSTONED"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx16CancelForget -v`
Expected: ImportError

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_lifecycle.py
git commit -m "test(sage): add failing tests for TX16 CANCEL_FORGET"
```

---

## Task 6: Implement TX16 CANCEL_FORGET

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement tx16_cancel_forget function**

```python
async def tx16_cancel_forget(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    agent_id: str,
) -> CancelForgetResult:
    """TX16 CANCEL_FORGET: Restore a tombstoned node within cancel window."""
    from context_service.db import queries as q

    node_result = await store.execute_query(q.GET_NODE_FOR_FORGET, {
        "node_id": node_id,
        "silo_id": silo_id,
    })

    if not node_result:
        raise InvariantViolation("NODE_NOT_FOUND", "Node not found")

    node = node_result[0]
    state = node.get("state")

    if state != NodeState.TOMBSTONED.value:
        raise InvariantViolation("NOT_TOMBSTONED", f"Node is not tombstoned (state: {state})")

    cancel_expires = node.get("cancel_window_expires")
    if cancel_expires:
        expires_dt = datetime.fromisoformat(cancel_expires.replace("Z", "+00:00"))
        if datetime.now(UTC) > expires_dt:
            raise InvariantViolation("CANCEL_WINDOW_EXPIRED", "Cancel window has expired")

    now = datetime.now(UTC)

    restore_result = await store.execute_write(q.RESTORE_TOMBSTONED_NODE, {
        "node_id": node_id,
        "silo_id": silo_id,
        "now": now.isoformat(),
        "restored_at": now.isoformat(),
        "agent_id": agent_id,
    })

    previous_state_str = restore_result[0].get("previous_state", "ACTIVE") if restore_result else "ACTIVE"
    previous_state = NodeState(previous_state_str)

    logger.debug("tx16_cancel_forget_complete", node_id=node_id, silo_id=silo_id)

    return CancelForgetResult(
        node_id=uuid.UUID(node_id),
        restored_at=now,
        previous_state=previous_state,
    )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx16CancelForget -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX16 CANCEL_FORGET transaction"
```

---

## Task 7: Write Failing Tests for CASCADE_STALENESS

**Files:**
- Modify: `tests/sage/test_lifecycle.py`

- [ ] **Step 1: Add imports for cascade_staleness**

Add `cascade_staleness, SynthesisState` to imports.

- [ ] **Step 2: Add TestCascadeStaleness class**

```python
class TestCascadeStaleness:
    """Tests for CASCADE_STALENESS helper."""

    @pytest.mark.asyncio
    async def test_marks_dependent_beliefs_stale(self, mock_store: AsyncMock) -> None:
        """Test that cascade marks dependent wisdom-layer nodes as stale."""
        node_id = make_uuid()
        belief_id = make_uuid()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": belief_id, "layer": "wisdom", "edge_type": "SYNTHESIZED_FROM"}
        ])

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=1,
        )

        assert count >= 1
        mock_store.execute_write.assert_called()

    @pytest.mark.asyncio
    async def test_respects_depth_limit(self, mock_store: AsyncMock) -> None:
        """Test that cascade stops at MAX_CASCADE_DEPTH."""
        node_id = make_uuid()

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=MAX_CASCADE_DEPTH + 1,
        )

        assert count == 0
        mock_store.execute_query.assert_not_called()

    @pytest.mark.asyncio
    async def test_deduplicates_visited_nodes(self, mock_store: AsyncMock) -> None:
        """Test that cascade doesn't revisit already-visited nodes."""
        node_id = make_uuid()
        visited = {node_id}

        count = await cascade_staleness(
            store=mock_store,
            node_id=node_id,
            silo_id="test-silo",
            depth=1,
            visited=visited,
        )

        assert count == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestCascadeStaleness -v`
Expected: ImportError

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_lifecycle.py
git commit -m "test(sage): add failing tests for CASCADE_STALENESS"
```

---

## Task 8: Implement CASCADE_STALENESS

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement cascade_staleness function**

```python
async def cascade_staleness(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    depth: int = 1,
    visited: set[str] | None = None,
) -> int:
    """CASCADE_STALENESS: Propagate staleness to dependent nodes.

    Depth-limited (MAX_CASCADE_DEPTH). Sync for depth 1, async events for deeper.
    Returns count of nodes marked stale.
    """
    from context_service.db import queries as q

    if depth > MAX_CASCADE_DEPTH:
        logger.warning("cascade_depth_limit_reached", node_id=node_id, depth=depth)
        return 0

    if visited is None:
        visited = set()

    if node_id in visited:
        return 0

    visited.add(node_id)

    # Find dependents
    dependents = await store.execute_query(q.GET_DEPENDENTS_FOR_CASCADE, {
        "node_id": node_id,
        "silo_id": silo_id,
    })

    cascade_count = 0

    for dep in dependents:
        dep_id = dep["id"]
        layer = dep.get("layer")

        if layer == "wisdom":
            # Mark belief stale
            await store.execute_write(q.MARK_BELIEF_STALE, {
                "node_id": dep_id,
                "silo_id": silo_id,
            })
            cascade_count += 1

        # Recurse (sync for depth 1, would be async for deeper in production)
        if depth == 1:
            cascade_count += await cascade_staleness(store, dep_id, silo_id, depth + 1, visited)

    logger.debug("cascade_staleness_complete", node_id=node_id, cascade_count=cascade_count, depth=depth)

    return cascade_count
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestCascadeStaleness -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement CASCADE_STALENESS helper"
```

---

## Task 9: Write Failing Tests for TX10 HARD_DELETE

**Files:**
- Modify: `tests/sage/test_lifecycle.py`

- [ ] **Step 1: Add imports for TX10**

Add `tx10_hard_delete` to imports.

- [ ] **Step 2: Add TestTx10HardDelete class**

```python
class TestTx10HardDelete:
    """Tests for TX10 HARD_DELETE."""

    @pytest.mark.asyncio
    async def test_deletes_expired_tombstoned_nodes(self, mock_store: AsyncMock) -> None:
        """Test that TX10 deletes nodes past cancel window."""
        node_id = make_uuid()
        past_time = (datetime.now(UTC) - timedelta(hours=2)).isoformat()

        mock_store.execute_query = AsyncMock(return_value=[
            {"id": node_id}
        ])
        mock_store.execute_write = AsyncMock(return_value=[{"deleted_count": 1}])

        result = await tx10_hard_delete(
            store=mock_store,
            silo_id="test-silo",
            batch_size=100,
        )

        assert isinstance(result, HardDeleteResult)
        assert result.deleted_count >= 1

    @pytest.mark.asyncio
    async def test_skips_unexpired_nodes(self, mock_store: AsyncMock) -> None:
        """Test that TX10 skips nodes still in cancel window."""
        mock_store.execute_query = AsyncMock(return_value=[])

        result = await tx10_hard_delete(
            store=mock_store,
            silo_id="test-silo",
            batch_size=100,
        )

        assert result.deleted_count == 0
        assert result.skipped_count == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx10HardDelete -v`
Expected: ImportError

- [ ] **Step 4: Commit failing tests**

```bash
git add tests/sage/test_lifecycle.py
git commit -m "test(sage): add failing tests for TX10 HARD_DELETE"
```

---

## Task 10: Implement TX10 HARD_DELETE

**Files:**
- Modify: `src/context_service/sage/transactions.py`

- [ ] **Step 1: Implement tx10_hard_delete function**

```python
async def tx10_hard_delete(
    store: HyperGraphStore,
    silo_id: str,
    batch_size: int = 100,
) -> HardDeleteResult:
    """TX10 HARD_DELETE: Permanently remove tombstoned nodes past cancel window.

    Called by scheduled GC job, not by agents directly.
    """
    from context_service.db import queries as q

    now = datetime.now(UTC)

    # Find tombstoned nodes past cancel window
    candidates = await store.execute_query(q.GET_TOMBSTONED_FOR_GC, {
        "silo_id": silo_id,
        "now": now.isoformat(),
        "batch_size": batch_size,
    })

    deleted_ids: list[str] = []
    skipped_count = 0

    for candidate in candidates:
        node_id = candidate["id"]

        try:
            # Delete edges first
            await store.execute_write(q.DELETE_EDGES_FOR_NODE, {
                "node_id": node_id,
                "silo_id": silo_id,
            })

            # Delete node
            await store.execute_write(q.HARD_DELETE_NODE, {
                "node_id": node_id,
                "silo_id": silo_id,
            })

            deleted_ids.append(node_id)

        except Exception as e:
            logger.warning("hard_delete_failed", node_id=node_id, error=str(e))
            skipped_count += 1

    logger.info("tx10_hard_delete_complete", silo_id=silo_id, deleted_count=len(deleted_ids), skipped_count=skipped_count)

    return HardDeleteResult(
        deleted_count=len(deleted_ids),
        skipped_count=skipped_count,
        deleted_ids=deleted_ids,
    )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/sage/test_lifecycle.py::TestTx10HardDelete -v`
Expected: All 2 tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/transactions.py
git commit -m "feat(sage): implement TX10 HARD_DELETE transaction"
```

---

## Task 11: Run Full Test Suite and Type Check

- [ ] **Step 1: Run all Phase 4 tests**

Run: `uv run pytest tests/sage/test_lifecycle.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run existing tests**

Run: `uv run pytest tests/sage/ -v`
Expected: All tests PASS (no regressions)

- [ ] **Step 3: Run type checker**

Run: `uv run mypy src/context_service/sage/transactions.py --strict`
Expected: No new errors

- [ ] **Step 4: Run linter**

Run: `uv run ruff check src/context_service/sage/`
Expected: No errors

- [ ] **Step 5: Commit any fixes if needed**

```bash
git add -A
git commit -m "fix(sage): address type and lint issues in Phase 4 transactions"
```

---

## Task 12: Update Module Exports

**Files:**
- Modify: `src/context_service/sage/__init__.py`

- [ ] **Step 1: Add new exports**

Add to imports and __all__:
- ForgetResult
- CancelForgetResult
- HardDeleteResult
- tx10_hard_delete
- tx15_forget
- tx16_cancel_forget
- cascade_staleness
- CANCEL_WINDOW_DURATION_SECONDS
- MAX_CASCADE_DEPTH

- [ ] **Step 2: Verify imports work**

Run: `python -c "from context_service.sage import tx15_forget, tx16_cancel_forget, tx10_hard_delete, cascade_staleness; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add src/context_service/sage/__init__.py
git commit -m "feat(sage): export Phase 4 transactions from module"
```

---

## Task 13: Update Brain Architecture Plan

**Files:**
- Modify: `context/plans/2026-06-01-brain-architecture.md`

- [ ] **Step 1: Mark Phase 4 tasks complete**

- [ ] **Step 2: Update status to "Phase 4 complete, Phase 5 next"**

- [ ] **Step 3: Commit**

```bash
git add context/plans/2026-06-01-brain-architecture.md
git commit -m "docs: mark Phase 4 tasks complete in brain architecture plan"
```

---

## Summary

This plan implements 4 items across 13 tasks:

| Transaction | Tests | Implementation |
|-------------|-------|----------------|
| TX15 FORGET | 4 tests | Task 3-4 |
| TX16 CANCEL_FORGET | 3 tests | Task 5-6 |
| CASCADE_STALENESS | 3 tests | Task 7-8 |
| TX10 HARD_DELETE | 2 tests | Task 9-10 |

Total: 12 new tests, ~250 lines of transaction code, ~60 lines of queries.
