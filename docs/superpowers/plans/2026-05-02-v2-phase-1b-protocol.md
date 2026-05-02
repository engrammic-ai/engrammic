# Phase 1b-A: Protocol Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `services/context.py` and `custodian/` to depend on `engine/protocols.py` instead of raw `MemgraphClient`, enabling in-memory test fakes.

**Architecture:** Extend HyperGraphStore protocol with missing methods, migrate callers method-by-method, add in-memory fake for testing, enforce boundary via CI check.

**Tech Stack:** Python Protocol classes, pytest, grep-based CI check

---

## File Structure

**Protocol extension:**
- Modify: `src/context_service/engine/protocols.py`

**Service migration:**
- Modify: `src/context_service/services/context.py`
- Modify: `src/context_service/api/deps.py` (dependency injection)

**Custodian migration (10 files):**
- Modify: `src/context_service/custodian/dispatch.py`
- Modify: `src/context_service/custodian/visit.py`
- Modify: `src/context_service/custodian/validators.py`
- Modify: `src/context_service/custodian/business_rules.py`
- Modify: `src/context_service/custodian/write_path.py`
- Modify: `src/context_service/custodian/consensus_promotion.py`
- Modify: `src/context_service/custodian/supersession.py`
- Modify: `src/context_service/custodian/agents.py`
- Modify: `src/context_service/custodian/silo_synthesis.py`
- Modify: `src/context_service/custodian/supersession_parser.py`

**Test fake:**
- Create: `tests/fakes/memgraph_fake.py`

**CI check:**
- Create: `scripts/check_protocol_boundary.sh`
- Modify: `.github/workflows/ci.yml` (or justfile)

---

## Task 1: Audit Protocol Gaps

**Files:**
- Read: `src/context_service/engine/protocols.py`
- Read: `src/context_service/services/context.py`
- Read: `src/context_service/custodian/*.py`

- [ ] **Step 1: List all MemgraphClient methods used in services/context.py**

```bash
rg "self\.(client|_client)\.\w+" src/context_service/services/context.py -o | sort | uniq
```

- [ ] **Step 2: List all MemgraphClient methods used in custodian/**

```bash
rg "client\.\w+|self\.client\.\w+" src/context_service/custodian/ -o | sort | uniq
```

- [ ] **Step 3: Compare against HyperGraphStore protocol**

```bash
rg "async def \w+" src/context_service/engine/protocols.py
```

- [ ] **Step 4: Document gap list**

Create a text file listing methods that need to be added to the protocol:
- `execute_write(query, params)` - raw Cypher write
- `execute_read(query, params)` - raw Cypher read
- `transaction()` - context manager for transactions
- Any other missing methods

---

## Task 2: Extend Protocol with Missing Methods

**Files:**
- Modify: `src/context_service/engine/protocols.py`
- Test: `tests/engine/test_protocol_compliance.py`

- [ ] **Step 1: Write protocol compliance test**

Create `tests/engine/test_protocol_compliance.py`:

```python
"""Test that MemgraphStore implements HyperGraphStore protocol."""

from typing import runtime_checkable
from context_service.engine.protocols import HyperGraphStore
from context_service.engine.memgraph_store import MemgraphStore


def test_memgraph_store_implements_protocol():
    """MemgraphStore should implement HyperGraphStore protocol."""
    assert isinstance(MemgraphStore, type)
    # Check key methods exist
    assert hasattr(MemgraphStore, "execute_write")
    assert hasattr(MemgraphStore, "execute_read")
    assert hasattr(MemgraphStore, "transaction")
```

- [ ] **Step 2: Add missing protocol methods**

Add to `HyperGraphStore` in `protocols.py`:

```python
from typing import Any, AsyncContextManager
from contextlib import asynccontextmanager

class HyperGraphStore(Protocol):
    # ... existing methods ...
    
    async def execute_write(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a write query and return results."""
        ...
    
    async def execute_read(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a read query and return results."""
        ...
    
    def transaction(self) -> AsyncContextManager[Any]:
        """Return an async context manager for transactions."""
        ...
```

- [ ] **Step 3: Run test to verify MemgraphStore complies**

```bash
uv run pytest tests/engine/test_protocol_compliance.py -v
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/protocols.py tests/engine/test_protocol_compliance.py
git commit -m "feat: extend HyperGraphStore protocol with execute_write/read and transaction"
```

---

## Task 3: Create In-Memory Protocol Fake

**Files:**
- Create: `tests/fakes/__init__.py`
- Create: `tests/fakes/memgraph_fake.py`
- Test: `tests/fakes/test_memgraph_fake.py`

- [ ] **Step 1: Create fakes package**

```bash
mkdir -p tests/fakes
touch tests/fakes/__init__.py
```

- [ ] **Step 2: Write test for fake store**

Create `tests/fakes/test_memgraph_fake.py`:

```python
"""Test the in-memory HyperGraphStore fake."""

import pytest
import uuid
from tests.fakes.memgraph_fake import InMemoryGraphStore
from context_service.engine.models import Node


@pytest.mark.asyncio
async def test_upsert_and_get_node():
    """Should store and retrieve nodes."""
    store = InMemoryGraphStore()
    
    node = Node(
        id=uuid.uuid4(),
        silo_id="silo-1",
        type="memory",
        content="Test content",
    )
    
    await store.upsert_node(node)
    retrieved = await store.get_node(node.id, "silo-1")
    
    assert retrieved is not None
    assert retrieved.content == "Test content"


@pytest.mark.asyncio
async def test_silo_isolation():
    """Nodes in different silos should be isolated."""
    store = InMemoryGraphStore()
    
    node_id = uuid.uuid4()
    node = Node(id=node_id, silo_id="silo-1", type="memory", content="Test")
    
    await store.upsert_node(node)
    
    # Should find in correct silo
    assert await store.get_node(node_id, "silo-1") is not None
    # Should not find in wrong silo
    assert await store.get_node(node_id, "silo-2") is None


@pytest.mark.asyncio
async def test_execute_write_returns_results():
    """execute_write should accept queries and return results."""
    store = InMemoryGraphStore()
    
    result = await store.execute_write(
        "CREATE (n:Test {id: $id}) RETURN n.id AS id",
        {"id": "test-1"},
    )
    
    assert isinstance(result, list)
```

- [ ] **Step 3: Implement InMemoryGraphStore**

Create `tests/fakes/memgraph_fake.py`:

```python
"""In-memory implementation of HyperGraphStore for testing.

This fake provides dict-backed storage with basic transaction support.
It does NOT implement full Cypher semantics - just enough for tests.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator

from context_service.engine.models import BinaryEdge, HyperEdge, Node


@dataclass
class InMemoryGraphStore:
    """Dict-backed graph store for unit testing."""
    
    _nodes: dict[tuple[uuid.UUID, str], Node] = field(default_factory=dict)
    _binary_edges: dict[tuple[uuid.UUID, str], BinaryEdge] = field(default_factory=dict)
    _hyperedges: dict[tuple[uuid.UUID, str], HyperEdge] = field(default_factory=dict)
    _in_transaction: bool = False
    _tx_snapshot: dict[str, Any] | None = None
    
    # --- Node CRUD ---
    
    async def upsert_node(self, node: Node) -> None:
        key = (node.id, node.silo_id)
        self._nodes[key] = node
    
    async def get_node(self, node_id: uuid.UUID, silo_id: str) -> Node | None:
        return self._nodes.get((node_id, silo_id))
    
    async def batch_get_nodes(
        self, node_ids: list[uuid.UUID], silo_id: str
    ) -> dict[uuid.UUID, Node]:
        return {
            nid: node
            for nid in node_ids
            if (node := self._nodes.get((nid, silo_id))) is not None
        }
    
    async def delete_node(self, node_id: uuid.UUID, silo_id: str) -> bool:
        key = (node_id, silo_id)
        if key in self._nodes:
            del self._nodes[key]
            return True
        return False
    
    async def find_nodes(
        self,
        silo_id: uuid.UUID,
        *,
        type: str | None = None,
        limit: int = 100,
        cursor: str | None = None,
    ) -> tuple[list[Node], str | None]:
        nodes = [
            n for (nid, sid), n in self._nodes.items()
            if sid == str(silo_id) and (type is None or n.type == type)
        ]
        return nodes[:limit], None
    
    async def count_nodes(self, silo_id: uuid.UUID) -> int:
        return sum(1 for (_, sid) in self._nodes if sid == str(silo_id))
    
    async def count_edges_in_silo(self, silo_id: uuid.UUID) -> int:
        return sum(1 for (_, sid) in self._binary_edges if sid == str(silo_id))
    
    async def sum_content_bytes_in_silo(self, silo_id: uuid.UUID) -> int:
        return sum(
            len(n.content.encode()) if n.content else 0
            for (_, sid), n in self._nodes.items()
            if sid == str(silo_id)
        )
    
    # --- Raw query execution (for compatibility) ---
    
    async def execute_write(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a write query. Returns empty list by default."""
        # Fake implementation - real tests should use higher-level methods
        return []
    
    async def execute_read(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a read query. Returns empty list by default."""
        return []
    
    # --- Transaction support ---
    
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        """Provide transaction context with rollback on error."""
        self._in_transaction = True
        self._tx_snapshot = {
            "nodes": dict(self._nodes),
            "edges": dict(self._binary_edges),
            "hyperedges": dict(self._hyperedges),
        }
        try:
            yield
        except Exception:
            # Rollback
            self._nodes = self._tx_snapshot["nodes"]
            self._binary_edges = self._tx_snapshot["edges"]
            self._hyperedges = self._tx_snapshot["hyperedges"]
            raise
        finally:
            self._in_transaction = False
            self._tx_snapshot = None
    
    # --- Health check ---
    
    async def health_check(self) -> bool:
        return True
```

- [ ] **Step 4: Run fake tests**

```bash
uv run pytest tests/fakes/test_memgraph_fake.py -v
```

- [ ] **Step 5: Commit**

```bash
git add tests/fakes/
git commit -m "feat: add InMemoryGraphStore fake for testing"
```

---

## Task 4: Migrate services/context.py to Protocol

**Files:**
- Modify: `src/context_service/services/context.py`
- Modify: `src/context_service/api/deps.py`

This is the largest migration. Do it method-by-method, keeping tests green at each step.

- [ ] **Step 1: Change type hint in constructor**

In `services/context.py`, change:
```python
def __init__(self, client: MemgraphClient, ...):
```
To:
```python
from context_service.engine.protocols import HyperGraphStore

def __init__(self, store: HyperGraphStore, ...):
```

- [ ] **Step 2: Update all self.client references to self.store**

```bash
# Find all references
rg "self\.client\." src/context_service/services/context.py
```

Replace `self.client` with `self.store` throughout.

- [ ] **Step 3: Run typecheck**

```bash
just typecheck
```

Fix any type errors.

- [ ] **Step 4: Update deps.py to pass store**

In `api/deps.py`, ensure the ContextService receives the store:

```python
async def get_context_service(
    store: HyperGraphStore = Depends(get_graph_store),
) -> ContextService:
    return ContextService(store=store, ...)
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/services/test_context.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/services/context.py src/context_service/api/deps.py
git commit -m "refactor: migrate services/context.py to HyperGraphStore protocol"
```

---

## Task 5: Migrate Custodian Files to Protocol

**Files:** All 10 custodian files that import MemgraphClient

- [ ] **Step 1: List all custodian files with direct imports**

```bash
rg "from context_service.stores.memgraph import" src/context_service/custodian/ -l
```

- [ ] **Step 2: Migrate custodian/dispatch.py**

Change import and type hint:
```python
# Before
from context_service.stores.memgraph import MemgraphClient

# After
from context_service.engine.protocols import HyperGraphStore
```

Update constructor and all `client` references.

- [ ] **Step 3: Run tests after dispatch.py**

```bash
uv run pytest tests/custodian/test_dispatch.py -v
```

- [ ] **Step 4: Migrate custodian/visit.py**

Same pattern. Update imports and type hints.

- [ ] **Step 5: Migrate custodian/validators.py**

Same pattern.

- [ ] **Step 6: Migrate custodian/business_rules.py**

Same pattern.

- [ ] **Step 7: Migrate custodian/write_path.py**

Same pattern.

- [ ] **Step 8: Migrate custodian/consensus_promotion.py**

Same pattern.

- [ ] **Step 9: Migrate custodian/supersession.py**

Same pattern.

- [ ] **Step 10: Migrate custodian/agents.py**

Same pattern.

- [ ] **Step 11: Migrate remaining custodian files**

- `silo_synthesis.py`
- `supersession_parser.py`
- Any others found in Step 1

- [ ] **Step 12: Run full custodian tests**

```bash
uv run pytest tests/custodian/ -v
```

- [ ] **Step 13: Commit**

```bash
git add src/context_service/custodian/
git commit -m "refactor: migrate custodian/ to HyperGraphStore protocol"
```

---

## Task 6: Add CI Boundary Check

**Files:**
- Create: `scripts/check_protocol_boundary.sh`
- Modify: `justfile`

- [ ] **Step 1: Create boundary check script**

Create `scripts/check_protocol_boundary.sh`:

```bash
#!/usr/bin/env bash
# Check that MemgraphClient is not imported outside allowed modules.
# Allowed: engine/, stores/, db/, tests/fakes/

set -e

VIOLATIONS=$(rg "from context_service.stores.memgraph import MemgraphClient" \
    src/context_service/ \
    --type py \
    -l \
    | grep -v "engine/" \
    | grep -v "stores/" \
    | grep -v "db/" \
    || true)

if [ -n "$VIOLATIONS" ]; then
    echo "ERROR: Direct MemgraphClient imports found outside allowed modules:"
    echo "$VIOLATIONS"
    echo ""
    echo "These files should depend on engine/protocols.py instead."
    exit 1
fi

echo "Protocol boundary check passed."
```

- [ ] **Step 2: Make script executable**

```bash
chmod +x scripts/check_protocol_boundary.sh
```

- [ ] **Step 3: Add to justfile**

Add recipe:
```makefile
# Check protocol boundary
check-protocol-boundary:
    ./scripts/check_protocol_boundary.sh
```

- [ ] **Step 4: Run boundary check**

```bash
just check-protocol-boundary
```

Expected: Pass (no violations)

- [ ] **Step 5: Commit**

```bash
git add scripts/check_protocol_boundary.sh justfile
git commit -m "ci: add protocol boundary check"
```

---

## Task 7: Migrate One Integration Test to Use Fake

**Files:**
- Modify: `tests/integration/test_context_service.py` (or similar)

- [ ] **Step 1: Find a suitable integration test**

```bash
ls tests/integration/
```

- [ ] **Step 2: Create a parallel unit test using the fake**

Create `tests/services/test_context_with_fake.py`:

```python
"""Test ContextService with in-memory fake store."""

import pytest
import uuid
from tests.fakes.memgraph_fake import InMemoryGraphStore
from context_service.services.context import ContextService


@pytest.fixture
def fake_store():
    return InMemoryGraphStore()


@pytest.fixture
def context_service(fake_store):
    # Create service with fake store
    return ContextService(store=fake_store)


@pytest.mark.asyncio
async def test_store_and_get(context_service, fake_store):
    """Basic store/get should work with fake store."""
    silo_id = "test-silo"
    
    # Store a node
    node_id = await context_service.store(
        content="Test content",
        silo_id=silo_id,
        type="memory",
    )
    
    # Retrieve it
    node = await context_service.get(node_id, silo_id=silo_id)
    
    assert node is not None
    assert node.content == "Test content"
```

- [ ] **Step 3: Run the fake-based test**

```bash
uv run pytest tests/services/test_context_with_fake.py -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/services/test_context_with_fake.py
git commit -m "test: demo ContextService test using InMemoryGraphStore fake"
```

---

## Task 8: Final Verification

- [ ] **Step 1: Run all quality checks**

```bash
just check
```

- [ ] **Step 2: Run full test suite**

```bash
just test
```

- [ ] **Step 3: Run boundary check**

```bash
just check-protocol-boundary
```

- [ ] **Step 4: Verify no direct imports remain**

```bash
rg "from context_service.stores.memgraph import MemgraphClient" src/context_service/services/ src/context_service/custodian/
```

Expected: No output (no violations)

- [ ] **Step 5: Create PR**

```bash
git push -u origin phase-v2-1b-protocol
gh pr create --title "Phase 1b-A: Protocol adoption for services + custodian" --body "$(cat <<'EOF'
## Summary
- Extended HyperGraphStore protocol with execute_write/read and transaction
- Migrated services/context.py to depend on protocol
- Migrated all custodian/ files (10) to depend on protocol
- Added InMemoryGraphStore fake for testing
- Added CI boundary check to prevent regression

## Test plan
- [x] All existing tests pass
- [x] Protocol compliance test
- [x] Fake store tests
- [x] Demo test using fake store
- [x] Boundary check passes

Spec: docs/superpowers/specs/2026-05-02-arch-cleanup-perf-rest-api.md
EOF
)"
```
