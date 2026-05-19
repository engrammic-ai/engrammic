# Supersession Head Pointer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O(1) supersession chain head lookups using linked-list pointers instead of O(n) edge walks.

**Architecture:** Each node stores `tail_id` (set once at supersession, immutable) pointing to the chain's oldest node. The tail node stores `head_id` (updated on each supersession) pointing to the current head. Query: lookup input's tail, read tail's head. Two indexed lookups, no traversal.

**Tech Stack:** Memgraph (Cypher), Python 3.12, pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/engine/queries.py` | Cypher query constants for supersession |
| `src/context_service/db/queries.py` | Belief/Commitment supersession queries |
| `src/context_service/engine/memgraph_store.py` | Store methods calling queries |
| `tests/engine/test_supersession_pointer.py` | Unit tests for pointer logic |
| `scripts/backfill_chain_pointers.py` | One-time backfill for existing chains |

---

## Task 1: Add Pointer Update to CREATE_CROSS_NODE_SUPERSEDES

**Files:**
- Modify: `src/context_service/engine/queries.py:334-345`
- Test: `tests/engine/test_supersession_pointer.py` (new)

- [ ] **Step 1: Write failing test for tail_id/head_id after supersession**

Create `tests/engine/test_supersession_pointer.py`:

```python
"""Tests for supersession chain pointer optimization."""

import uuid
from datetime import UTC, datetime

import pytest

from context_service.engine.memgraph_store import MemgraphStore


@pytest.fixture
def silo_id() -> str:
    return f"test-silo-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def now() -> datetime:
    return datetime.now(UTC)


@pytest.mark.asyncio
async def test_supersession_sets_tail_and_head_pointers(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """When B supersedes A, A becomes tail with head_id=B, B gets tail_id=A."""
    # Create two nodes: A (older) and B (newer)
    node_a_id = uuid.uuid4()
    node_b_id = uuid.uuid4()

    await memgraph_store._client.execute_write(
        """
        CREATE (a:Node:Claim {id: $a_id, silo_id: $silo_id, content: 'claim A', valid_from: $vf})
        CREATE (b:Node:Claim {id: $b_id, silo_id: $silo_id, content: 'claim B', valid_from: $vf})
        """,
        {"a_id": str(node_a_id), "b_id": str(node_b_id), "silo_id": silo_id, "vf": now.isoformat()},
    )

    # B supersedes A
    created = await memgraph_store.create_supersedes_edge(
        from_id=node_b_id,
        to_id=node_a_id,
        silo_id=silo_id,
        valid_from=now,
    )
    assert created

    # Verify pointers
    result = await memgraph_store._client.execute_query(
        """
        MATCH (a:Claim {id: $a_id, silo_id: $silo_id})
        MATCH (b:Claim {id: $b_id, silo_id: $silo_id})
        RETURN a.head_id AS a_head, a.tail_id AS a_tail,
               b.head_id AS b_head, b.tail_id AS b_tail
        """,
        {"a_id": str(node_a_id), "b_id": str(node_b_id), "silo_id": silo_id},
    )
    row = result[0]
    # A is tail: has head_id pointing to B, no tail_id
    assert row["a_head"] == str(node_b_id)
    assert row["a_tail"] is None
    # B is head: has tail_id pointing to A, no head_id
    assert row["b_tail"] == str(node_a_id)
    assert row["b_head"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_supersession_sets_tail_and_head_pointers -v`

Expected: FAIL - `a_head` is None (pointer not set yet)

- [ ] **Step 3: Update CREATE_CROSS_NODE_SUPERSEDES query**

In `src/context_service/engine/queries.py`, replace lines 334-345:

```python
# Cross-node SUPERSEDES for Custodian-detected semantic supersession.
# Sets tail_id on new node, head_id on tail node for O(1) chain lookups.
CREATE_CROSS_NODE_SUPERSEDES = f"""
MATCH (new) WHERE {content_union_predicate("new")} AND new.id = $from_id AND new.silo_id = $silo_id
MATCH (old) WHERE {content_union_predicate("old")} AND old.id = $to_id AND old.silo_id = $silo_id
WHERE new <> old
MERGE (new)-[r:SUPERSEDES {{source: $source, reason: $reason}}]->(old)
ON CREATE SET r.created_at = $valid_from
WITH old, new, r
// Set valid_to on old if not already set
FOREACH (_ IN CASE WHEN old.valid_to IS NULL THEN [1] ELSE [] END |
  SET old.valid_to = $valid_from
)
WITH old, new
// Derive tail_id: old's tail_id if it exists (old was head of a chain), else old is the tail
WITH old, new, COALESCE(old.tail_id, old.id) AS tail_id
SET new.tail_id = tail_id
WITH new, tail_id
// Update tail's head_id to point to new head
MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
SET tail.head_id = new.id
RETURN count(*) AS created
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_supersession_sets_tail_and_head_pointers -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/queries.py tests/engine/test_supersession_pointer.py
git commit -m "feat(supersession): add tail_id/head_id pointers on cross-node supersession"
```

---

## Task 2: Test Chain Extension (C supersedes B supersedes A)

**Files:**
- Test: `tests/engine/test_supersession_pointer.py`

- [ ] **Step 1: Write test for chain extension**

Add to `tests/engine/test_supersession_pointer.py`:

```python
@pytest.mark.asyncio
async def test_chain_extension_updates_tail_head_pointer(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """When C supersedes B (which superseded A), tail A's head_id updates to C."""
    node_a_id, node_b_id, node_c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    # Create three nodes
    await memgraph_store._client.execute_write(
        """
        CREATE (a:Node:Claim {id: $a_id, silo_id: $silo_id, content: 'A', valid_from: $vf})
        CREATE (b:Node:Claim {id: $b_id, silo_id: $silo_id, content: 'B', valid_from: $vf})
        CREATE (c:Node:Claim {id: $c_id, silo_id: $silo_id, content: 'C', valid_from: $vf})
        """,
        {
            "a_id": str(node_a_id),
            "b_id": str(node_b_id),
            "c_id": str(node_c_id),
            "silo_id": silo_id,
            "vf": now.isoformat(),
        },
    )

    # B supersedes A
    await memgraph_store.create_supersedes_edge(
        from_id=node_b_id, to_id=node_a_id, silo_id=silo_id, valid_from=now
    )
    # C supersedes B
    await memgraph_store.create_supersedes_edge(
        from_id=node_c_id, to_id=node_b_id, silo_id=silo_id, valid_from=now
    )

    # Verify pointers
    result = await memgraph_store._client.execute_query(
        """
        MATCH (a:Claim {id: $a_id, silo_id: $silo_id})
        MATCH (b:Claim {id: $b_id, silo_id: $silo_id})
        MATCH (c:Claim {id: $c_id, silo_id: $silo_id})
        RETURN a.head_id AS a_head, a.tail_id AS a_tail,
               b.head_id AS b_head, b.tail_id AS b_tail,
               c.head_id AS c_head, c.tail_id AS c_tail
        """,
        {
            "a_id": str(node_a_id),
            "b_id": str(node_b_id),
            "c_id": str(node_c_id),
            "silo_id": silo_id,
        },
    )
    row = result[0]
    # A is tail: head_id points to C (updated), no tail_id
    assert row["a_head"] == str(node_c_id)
    assert row["a_tail"] is None
    # B is middle: tail_id points to A, no head_id
    assert row["b_tail"] == str(node_a_id)
    assert row["b_head"] is None
    # C is head: tail_id points to A, no head_id
    assert row["c_tail"] == str(node_a_id)
    assert row["c_head"] is None
```

- [ ] **Step 2: Run test**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_chain_extension_updates_tail_head_pointer -v`

Expected: PASS (query from Task 1 handles this)

- [ ] **Step 3: Commit**

```bash
git add tests/engine/test_supersession_pointer.py
git commit -m "test(supersession): verify chain extension updates tail's head_id"
```

---

## Task 3: Add Fast-Path Query for Live-Tip Lookup

**Files:**
- Modify: `src/context_service/engine/queries.py` (add new query)
- Test: `tests/engine/test_supersession_pointer.py`

- [ ] **Step 1: Write failing test for fast-path lookup**

Add to `tests/engine/test_supersession_pointer.py`:

```python
@pytest.mark.asyncio
async def test_resolve_current_head_via_pointers(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """resolve_current_head returns chain head in O(1) via pointers."""
    node_a_id, node_b_id, node_c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    await memgraph_store._client.execute_write(
        """
        CREATE (a:Node:Claim {id: $a_id, silo_id: $silo_id, content: 'A', valid_from: $vf})
        CREATE (b:Node:Claim {id: $b_id, silo_id: $silo_id, content: 'B', valid_from: $vf})
        CREATE (c:Node:Claim {id: $c_id, silo_id: $silo_id, content: 'C', valid_from: $vf})
        """,
        {
            "a_id": str(node_a_id),
            "b_id": str(node_b_id),
            "c_id": str(node_c_id),
            "silo_id": silo_id,
            "vf": now.isoformat(),
        },
    )

    # Build chain: C -> B -> A
    await memgraph_store.create_supersedes_edge(
        from_id=node_b_id, to_id=node_a_id, silo_id=silo_id, valid_from=now
    )
    await memgraph_store.create_supersedes_edge(
        from_id=node_c_id, to_id=node_b_id, silo_id=silo_id, valid_from=now
    )

    # Lookup from any node should return C
    head_from_a = await memgraph_store.resolve_current_head(node_a_id, silo_id)
    head_from_b = await memgraph_store.resolve_current_head(node_b_id, silo_id)
    head_from_c = await memgraph_store.resolve_current_head(node_c_id, silo_id)

    assert head_from_a == node_c_id
    assert head_from_b == node_c_id
    assert head_from_c == node_c_id


@pytest.mark.asyncio
async def test_resolve_current_head_single_node(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """Single node with no supersession returns itself."""
    node_id = uuid.uuid4()

    await memgraph_store._client.execute_write(
        "CREATE (n:Node:Claim {id: $id, silo_id: $silo_id, content: 'solo', valid_from: $vf})",
        {"id": str(node_id), "silo_id": silo_id, "vf": now.isoformat()},
    )

    head = await memgraph_store.resolve_current_head(node_id, silo_id)
    assert head == node_id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_resolve_current_head_via_pointers -v`

Expected: FAIL - `resolve_current_head` method doesn't exist

- [ ] **Step 3: Add RESOLVE_CURRENT_HEAD query**

Add to `src/context_service/engine/queries.py` after `FILTER_SUPERSEDED_AT`:

```python
# Fast-path O(1) lookup for current chain head via pointers.
# Returns head_id for any node in a supersession chain.
# For nodes without pointers (not yet backfilled), returns null.
RESOLVE_CURRENT_HEAD = f"""
MATCH (input) WHERE {content_union_predicate("input")} AND input.id = $id AND input.silo_id = $silo_id
// Derive tail: input's tail_id if set, else input might be the tail itself
WITH input, COALESCE(input.tail_id, input.id) AS tail_id
// If input has no tail_id, check if input IS a tail (has head_id)
// or is a standalone node (no pointers at all)
OPTIONAL MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
WITH input, tail
// Return: tail's head_id if tail exists and has head_id, else input.id (standalone or is head)
RETURN COALESCE(tail.head_id, input.id) AS head_id
"""
```

- [ ] **Step 4: Add resolve_current_head method to MemgraphStore**

Add to `src/context_service/engine/memgraph_store.py` after `filter_superseded_at`:

```python
    async def resolve_current_head(
        self,
        node_id: uuid.UUID,
        silo_id: str,
    ) -> uuid.UUID | None:
        """Resolve the current chain head for a node using O(1) pointer lookup.

        Returns the head node's id, or the input id if it's standalone/head.
        Returns None if node doesn't exist.
        """
        result = await self._client.execute_query(
            queries.RESOLVE_CURRENT_HEAD,
            {"id": str(node_id), "silo_id": silo_id},
        )
        if not result:
            return None
        head_id = result[0].get("head_id")
        return uuid.UUID(head_id) if head_id else None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/engine/test_supersession_pointer.py -k "resolve_current_head" -v`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/engine/queries.py src/context_service/engine/memgraph_store.py tests/engine/test_supersession_pointer.py
git commit -m "feat(supersession): add resolve_current_head O(1) pointer lookup"
```

---

## Task 4: Update FILTER_SUPERSEDED_AT with Fast-Path

**Files:**
- Modify: `src/context_service/engine/queries.py:348-362`
- Test: `tests/engine/test_supersession_pointer.py`

- [ ] **Step 1: Write test for filter_superseded_at with pointers**

Add to `tests/engine/test_supersession_pointer.py`:

```python
@pytest.mark.asyncio
async def test_filter_superseded_at_uses_pointers(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """filter_superseded_at returns head for all nodes in chain."""
    node_a_id, node_b_id, node_c_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    await memgraph_store._client.execute_write(
        """
        CREATE (a:Node:Claim {id: $a_id, silo_id: $silo_id, content: 'A', valid_from: $vf})
        CREATE (b:Node:Claim {id: $b_id, silo_id: $silo_id, content: 'B', valid_from: $vf})
        CREATE (c:Node:Claim {id: $c_id, silo_id: $silo_id, content: 'C', valid_from: $vf})
        """,
        {
            "a_id": str(node_a_id),
            "b_id": str(node_b_id),
            "c_id": str(node_c_id),
            "silo_id": silo_id,
            "vf": now.isoformat(),
        },
    )

    # Build chain: C -> B -> A
    await memgraph_store.create_supersedes_edge(
        from_id=node_b_id, to_id=node_a_id, silo_id=silo_id, valid_from=now
    )
    await memgraph_store.create_supersedes_edge(
        from_id=node_c_id, to_id=node_b_id, silo_id=silo_id, valid_from=now
    )

    # All should map to C
    result = await memgraph_store.filter_superseded_at(
        node_ids=[node_a_id, node_b_id, node_c_id],
        silo_id=silo_id,
        as_of=now,
    )

    assert result[node_a_id] == node_c_id
    assert result[node_b_id] == node_c_id
    assert result[node_c_id] == node_c_id
```

- [ ] **Step 2: Run test (should pass with existing chain-walk)**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_filter_superseded_at_uses_pointers -v`

Expected: PASS (existing implementation works, just slower)

- [ ] **Step 3: Update FILTER_SUPERSEDED_AT with pointer fast-path**

Replace `FILTER_SUPERSEDED_AT` in `src/context_service/engine/queries.py`:

```python
# Batch version-check with O(1) pointer fast-path for live-tip lookups.
# Falls back to chain walk for historical as_of or missing pointers.
FILTER_SUPERSEDED_AT = f"""
UNWIND $ids AS input_id
MATCH (input) WHERE {content_union_predicate("input")} AND input.id = input_id AND input.silo_id = $silo_id

// Fast path: use pointers if available
WITH input_id, input, COALESCE(input.tail_id, input.id) AS tail_id
OPTIONAL MATCH (tail) WHERE {content_union_predicate("tail")} AND tail.id = tail_id AND tail.silo_id = $silo_id
WITH input_id, input, tail, COALESCE(tail.head_id, input.id) AS pointer_head_id

// Check if pointer head is valid at as_of
OPTIONAL MATCH (head) WHERE {content_union_predicate("head")} AND head.id = pointer_head_id AND head.silo_id = $silo_id
  AND coalesce(head.valid_from, head.created_at) <= $as_of
  AND (head.valid_to IS NULL OR head.valid_to > $as_of)

// If pointer head is valid, use it; otherwise fall back to chain walk
WITH input_id, input, head
WHERE head IS NOT NULL
RETURN input_id, head.id AS valid_id

UNION

// Fallback: chain walk for historical queries or missing pointers
UNWIND $ids AS input_id
MATCH (input) WHERE {content_union_predicate("input")} AND input.id = input_id AND input.silo_id = $silo_id

// Only fall back if pointer path didn't return a result
WITH input_id, input
WHERE input.tail_id IS NULL AND input.head_id IS NULL

OPTIONAL MATCH path = (tip)-[:SUPERSEDES*0..]->(input)
WHERE {content_union_predicate("tip")}
  AND tip.silo_id = $silo_id
  AND coalesce(tip.valid_from, tip.created_at) <= $as_of
  AND (tip.valid_to IS NULL OR tip.valid_to > $as_of)
WITH input_id, tip
WHERE tip IS NOT NULL
WITH input_id, tip
ORDER BY coalesce(tip.valid_from, tip.created_at) DESC
WITH input_id, collect(tip)[0] AS chosen
RETURN input_id, chosen.id AS valid_id
"""
```

- [ ] **Step 4: Run all supersession tests**

Run: `uv run pytest tests/engine/test_supersession_pointer.py -v`

Expected: PASS

- [ ] **Step 5: Run broader test suite to check for regressions**

Run: `uv run pytest tests/ -k "supersed" -v --tb=short`

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/context_service/engine/queries.py
git commit -m "feat(supersession): add pointer fast-path to FILTER_SUPERSEDED_AT"
```

---

## Task 5: Update Belief Supersession Queries

**Files:**
- Modify: `src/context_service/db/queries.py:822-839`
- Test: `tests/engine/test_supersession_pointer.py`

- [ ] **Step 1: Write test for belief supersession pointers**

Add to `tests/engine/test_supersession_pointer.py`:

```python
@pytest.mark.asyncio
async def test_belief_supersession_sets_pointers(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """Belief supersession sets tail_id/head_id pointers."""
    belief_a_id, belief_b_id = uuid.uuid4(), uuid.uuid4()

    await memgraph_store._client.execute_write(
        """
        CREATE (a:Node:Belief {id: $a_id, silo_id: $silo_id, content: 'belief A', valid_from: $vf})
        CREATE (b:Node:Belief {id: $b_id, silo_id: $silo_id, content: 'belief B', valid_from: $vf})
        """,
        {"a_id": str(belief_a_id), "b_id": str(belief_b_id), "silo_id": silo_id, "vf": now.isoformat()},
    )

    # Execute belief supersession query directly
    from context_service.db import queries as db_queries

    await memgraph_store._client.execute_write(
        db_queries.CREATE_BELIEF_SUPERSEDES,
        {
            "new_belief_id": str(belief_b_id),
            "old_belief_id": str(belief_a_id),
            "silo_id": silo_id,
            "reason": "evidence_shift",
            "created_at": now.isoformat(),
        },
    )

    # Verify pointers
    result = await memgraph_store._client.execute_query(
        """
        MATCH (a:Belief {id: $a_id, silo_id: $silo_id})
        MATCH (b:Belief {id: $b_id, silo_id: $silo_id})
        RETURN a.head_id AS a_head, b.tail_id AS b_tail
        """,
        {"a_id": str(belief_a_id), "b_id": str(belief_b_id), "silo_id": silo_id},
    )
    row = result[0]
    assert row["a_head"] == str(belief_b_id)
    assert row["b_tail"] == str(belief_a_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_belief_supersession_sets_pointers -v`

Expected: FAIL - pointers not set

- [ ] **Step 3: Update CREATE_BELIEF_SUPERSEDES**

In `src/context_service/db/queries.py`, replace lines 822-830:

```python
# Create :SUPERSEDES edge between Beliefs with pointer updates for O(1) lookups.
# Parameters: new_belief_id, old_belief_id, silo_id, reason (str), created_at (ISO datetime str).
CREATE_BELIEF_SUPERSEDES = """
MATCH (newer:Belief {id: $new_belief_id, silo_id: $silo_id})
MATCH (older:Belief {id: $old_belief_id, silo_id: $silo_id})
MERGE (newer)-[r:SUPERSEDES {
    reason: $reason,
    created_at: $created_at
}]->(older)
// Set pointers: newer gets tail_id, tail gets head_id
WITH newer, older, COALESCE(older.tail_id, older.id) AS tail_id
SET newer.tail_id = tail_id
WITH newer, tail_id
MATCH (tail:Belief {id: tail_id, silo_id: $silo_id})
SET tail.head_id = newer.id
RETURN tail.id AS tail_id
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_belief_supersession_sets_pointers -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/db/queries.py tests/engine/test_supersession_pointer.py
git commit -m "feat(supersession): add pointers to CREATE_BELIEF_SUPERSEDES"
```

---

## Task 6: Update CRYSTALLIZE_TO_COMMITMENT Query

**Files:**
- Modify: `src/context_service/db/queries.py:1305-1334`
- Test: `tests/engine/test_supersession_pointer.py`

- [ ] **Step 1: Write test for commitment supersession pointers**

Add to `tests/engine/test_supersession_pointer.py`:

```python
@pytest.mark.asyncio
async def test_crystallize_commitment_sets_pointers(
    memgraph_store: MemgraphStore,
    silo_id: str,
    now: datetime,
) -> None:
    """Crystallizing a hypothesis that supersedes existing commitment sets pointers."""
    wb_id = uuid.uuid4()
    cm_id = uuid.uuid4()
    existing_cm_id = uuid.uuid4()
    shared_node_id = uuid.uuid4()

    # Create shared node, existing commitment, and working hypothesis
    await memgraph_store._client.execute_write(
        """
        CREATE (shared:Node:Fact {id: $shared_id, silo_id: $silo_id, content: 'shared'})
        CREATE (existing:Node:Commitment {id: $existing_id, silo_id: $silo_id, layer: 'wisdom', content: 'old', valid_from: $vf})
        CREATE (wb:WorkingHypothesis {id: $wb_id, silo_id: $silo_id, content: 'new', confidence: 0.9})
        CREATE (existing)-[:ABOUT]->(shared)
        CREATE (wb)-[:ABOUT]->(shared)
        """,
        {
            "shared_id": str(shared_node_id),
            "existing_id": str(existing_cm_id),
            "wb_id": str(wb_id),
            "silo_id": silo_id,
            "vf": now.isoformat(),
        },
    )

    # Crystallize
    from context_service.db import queries as db_queries

    await memgraph_store._client.execute_write(
        db_queries.CRYSTALLIZE_TO_COMMITMENT,
        {
            "belief_id": str(wb_id),
            "commitment_id": str(cm_id),
            "silo_id": silo_id,
            "created_at": now.isoformat(),
            "valid_from": now.isoformat(),
            "reason": "crystallization",
        },
    )

    # Verify pointers: existing is tail with head_id, cm is head with tail_id
    result = await memgraph_store._client.execute_query(
        """
        MATCH (existing:Commitment {id: $existing_id, silo_id: $silo_id})
        MATCH (cm:Commitment {id: $cm_id, silo_id: $silo_id})
        RETURN existing.head_id AS existing_head, cm.tail_id AS cm_tail
        """,
        {"existing_id": str(existing_cm_id), "cm_id": str(cm_id), "silo_id": silo_id},
    )
    row = result[0]
    assert row["existing_head"] == str(cm_id)
    assert row["cm_tail"] == str(existing_cm_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_crystallize_commitment_sets_pointers -v`

Expected: FAIL - pointers not set

- [ ] **Step 3: Update CRYSTALLIZE_TO_COMMITMENT**

In `src/context_service/db/queries.py`, replace the CRYSTALLIZE_TO_COMMITMENT query (lines 1305-1334):

```python
# Crystallize a WorkingHypothesis into a Commitment, superseding any existing
# Commitments that share ABOUT targets. Sets tail_id/head_id for O(1) lookups.
CRYSTALLIZE_TO_COMMITMENT = """
MATCH (wb:WorkingHypothesis {id: $belief_id, silo_id: $silo_id})
CREATE (cm:Node:Commitment {
    id: $commitment_id,
    silo_id: $silo_id,
    layer: "wisdom",
    content: wb.content,
    confidence: wb.confidence,
    created_at: $created_at,
    valid_from: $valid_from,
    crystallized_from: wb.id
})
WITH wb, cm
MATCH (wb)-[:ABOUT]->(n)
CREATE (cm)-[:ABOUT]->(n)
WITH DISTINCT wb, cm
OPTIONAL MATCH (cm)-[:ABOUT]->(shared_node)<-[:ABOUT]-(existing:Commitment {silo_id: $silo_id})
WHERE existing.id <> cm.id
WITH wb, cm, collect(DISTINCT existing) AS candidates
DETACH DELETE wb
WITH cm, candidates
UNWIND (CASE WHEN size(candidates) = 0 THEN [null] ELSE candidates END) AS existing
WITH cm, existing WHERE existing IS NOT NULL
// Only supersede if existing is not already superseded
OPTIONAL MATCH (superseding:Commitment)-[:SUPERSEDES]->(existing)
WITH cm, existing, superseding WHERE superseding IS NULL
// Create supersession with pointers
WITH cm, existing, COALESCE(existing.tail_id, existing.id) AS tail_id
SET cm.tail_id = tail_id
CREATE (cm)-[:SUPERSEDES {reason: $reason, created_at: $created_at}]->(existing)
SET existing.valid_to = $valid_from
WITH cm, tail_id
MATCH (tail:Commitment {id: tail_id, silo_id: $silo_id})
SET tail.head_id = cm.id
RETURN cm.id AS commitment_id
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_supersession_pointer.py::test_crystallize_commitment_sets_pointers -v`

Expected: PASS

- [ ] **Step 5: Run full test suite for regressions**

Run: `uv run pytest tests/ -k "crystallize or commitment" -v --tb=short`

Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add src/context_service/db/queries.py tests/engine/test_supersession_pointer.py
git commit -m "feat(supersession): add pointers to CRYSTALLIZE_TO_COMMITMENT"
```

---

## Task 7: Add Backfill Script for Existing Chains

**Files:**
- Create: `scripts/backfill_chain_pointers.py`
- Test: Manual verification

- [ ] **Step 1: Create backfill script**

Create `scripts/backfill_chain_pointers.py`:

```python
#!/usr/bin/env python3
"""Backfill tail_id/head_id pointers for existing supersession chains.

Usage:
    uv run python scripts/backfill_chain_pointers.py --silo-id <silo> [--dry-run]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from context_service.config.logging import get_logger
from context_service.stores.memgraph import MemgraphClient

logger = get_logger(__name__)

# Find all chain tails (nodes that are superseded but don't supersede anything)
FIND_CHAIN_TAILS = """
MATCH (tail)<-[:SUPERSEDES]-(successor)
WHERE tail.silo_id = $silo_id
  AND NOT (tail)-[:SUPERSEDES]->()
  AND tail.head_id IS NULL
RETURN DISTINCT tail.id AS tail_id
LIMIT $batch_size
"""

# For a given tail, walk chain to find head and set pointers
BACKFILL_CHAIN = """
MATCH (tail) WHERE tail.id = $tail_id AND tail.silo_id = $silo_id
// Walk chain to find head (node with no incoming SUPERSEDES)
MATCH path = (head)-[:SUPERSEDES*0..]->(tail)
WHERE NOT ()-[:SUPERSEDES]->(head) AND head.silo_id = $silo_id
WITH tail, head, nodes(path) AS chain_nodes
// Set tail's head_id
SET tail.head_id = head.id
// Set tail_id on all nodes in chain except tail itself
WITH tail, head, chain_nodes
UNWIND chain_nodes AS node
WITH tail, head, node WHERE node.id <> tail.id
SET node.tail_id = tail.id
RETURN head.id AS head_id, count(*) AS nodes_updated
"""


async def backfill_silo(client: MemgraphClient, silo_id: str, dry_run: bool) -> int:
    """Backfill pointers for all chains in a silo."""
    total_chains = 0
    batch_size = 100

    while True:
        tails = await client.execute_query(
            FIND_CHAIN_TAILS, {"silo_id": silo_id, "batch_size": batch_size}
        )
        if not tails:
            break

        for row in tails:
            tail_id = row["tail_id"]
            if dry_run:
                logger.info(f"[dry-run] Would backfill chain with tail {tail_id}")
            else:
                result = await client.execute_write(
                    BACKFILL_CHAIN, {"tail_id": tail_id, "silo_id": silo_id}
                )
                if result:
                    head_id = result[0].get("head_id")
                    nodes = result[0].get("nodes_updated", 0)
                    logger.info(f"Backfilled chain: tail={tail_id} head={head_id} nodes={nodes}")
            total_chains += 1

    return total_chains


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill supersession chain pointers")
    parser.add_argument("--silo-id", required=True, help="Silo ID to backfill")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done")
    args = parser.parse_args()

    from context_service.config.settings import get_settings

    settings = get_settings()
    client = MemgraphClient(settings.memgraph_uri)

    try:
        total = await backfill_silo(client, args.silo_id, args.dry_run)
        logger.info(f"Backfill complete: {total} chains processed")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x scripts/backfill_chain_pointers.py
```

- [ ] **Step 3: Test dry-run locally**

Run: `uv run python scripts/backfill_chain_pointers.py --silo-id test-silo --dry-run`

Expected: Lists chains that would be backfilled (or "0 chains" if test DB is empty)

- [ ] **Step 4: Commit**

```bash
git add scripts/backfill_chain_pointers.py
git commit -m "feat(supersession): add backfill script for chain pointers"
```

---

## Task 8: Add Protocol Method and Update Fake Store

**Files:**
- Modify: `src/context_service/engine/protocols.py`
- Modify: `tests/fakes/fake_graph_store.py`

- [ ] **Step 1: Add resolve_current_head to protocol**

In `src/context_service/engine/protocols.py`, add after `filter_superseded_at`:

```python
    async def resolve_current_head(
        self,
        node_id: uuid.UUID,
        silo_id: str,
    ) -> uuid.UUID | None:
        """Resolve the current chain head for a node using O(1) pointer lookup.

        Returns the head node's id, or the input id if it's standalone/head.
        Returns None if node doesn't exist.
        """
        ...
```

- [ ] **Step 2: Add stub to FakeGraphStore**

In `tests/fakes/fake_graph_store.py`, add after `filter_superseded_at`:

```python
    async def resolve_current_head(
        self,
        node_id: uuid.UUID,
        silo_id: str,
    ) -> uuid.UUID | None:
        raise NotImplementedError("FakeGraphStore.resolve_current_head not implemented")
```

- [ ] **Step 3: Run type check**

Run: `uv run mypy src/context_service/engine/protocols.py tests/fakes/fake_graph_store.py`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/protocols.py tests/fakes/fake_graph_store.py
git commit -m "feat(supersession): add resolve_current_head to protocol"
```

---

## Task 9: Final Verification and Cleanup

**Files:**
- All modified files

- [ ] **Step 1: Run full type check**

Run: `uv run just check`

Expected: All pass

- [ ] **Step 2: Run full test suite**

Run: `uv run just test`

Expected: All pass

- [ ] **Step 3: Update plans README**

Move supersession head pointer from "Future work" to "Shipped" in `context/plans/README.md`:

In the "Shipped" section, add:
```markdown
- v2.11 Supersession Head Pointer (O(1) chain lookups via tail_id/head_id pointers)
```

Remove the "Supersession head pointer" row from the "Future work" table.

- [ ] **Step 4: Commit**

```bash
git add context/plans/README.md
git commit -m "docs: mark supersession head pointer as shipped"
```

---

## Done Criteria

- [ ] All supersession write paths set `tail_id` on new head and `head_id` on tail
- [ ] `resolve_current_head` returns O(1) head lookup via pointers
- [ ] `FILTER_SUPERSEDED_AT` uses pointer fast-path with chain-walk fallback
- [ ] Backfill script exists for existing chains
- [ ] All tests pass
- [ ] `just check` passes

---

Plan complete and saved to `docs/superpowers/plans/2026-05-19-supersession-head-pointer.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?