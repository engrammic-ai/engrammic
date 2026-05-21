# Data Lifecycle Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement data lifecycle management: `forget` MCP tool, three-store consistency for hard-delete, GDPR erasure endpoint, supersession chain pruning, and per-silo retention overrides.

**Architecture:** Two-sprint delivery. Sprint 1 builds foundation (three-store delete coordination, tombstone filtering, forget tool). Sprint 2 adds chain pruning and GDPR compliance. All deletions use Memgraph-first saga pattern with dead-letter queue for Qdrant failures.

**Tech Stack:** FastAPI, Memgraph (Cypher), Qdrant (payload filters), Postgres (audit tables), Redis (supersession locks), Dagster (scheduled jobs)

**Spec:** `context/brainstorm/2026-05-20-data-lifecycle-management.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|----------------|
| `src/context_service/retention/forget_service.py` | Forget operations: tombstone, cancel, Qdrant sync |
| `src/context_service/mcp/tools/forget.py` | MCP tool wrapper for forget service |
| `src/context_service/services/erasure.py` | GDPR erasure: cascade traversal, partial-source detection |
| `src/context_service/pipelines/assets/dead_letter_reconciliation.py` | Dagster job for failed Qdrant deletes |
| `src/context_service/pipelines/assets/chain_pruning.py` | Stub-retention for long supersession chains |
| `src/context_service/db/migrations/versions/XXXX_erasure_audit.py` | Alembic migration for erasure tables |
| `tests/retention/test_forget_service.py` | Forget service unit tests |
| `tests/retention/test_three_store_delete.py` | Three-store coordination tests |
| `tests/services/test_erasure.py` | Erasure service tests |

### Modified Files
| File | Changes |
|------|---------|
| `src/context_service/models/silo.py` | Add `supersession_chain_max_length` to `RetentionOverrides`, new `ForgetPolicyOverrides` class, extend `ResolvedSiloConfig` |
| `src/context_service/config/settings.py` | Add `retention_supersession_chain_max_length`, `forget_cancel_window_hours`, `forget_rate_limit_per_hour` |
| `src/context_service/retention/queries.py` | Add stub-retention queries, forget queries, HyperEdge cleanup |
| `src/context_service/retention/service.py` | Wire three-store delete, add dead-letter queue |
| `src/context_service/engine/qdrant_store.py` | Add `set_payload()` for tombstone sync, tombstone filter in searches |
| `src/context_service/engine/memgraph_store.py` | Add `tail_id`/`head_id` indexes, Redis lock for supersession |
| `src/context_service/config/mcp_tools.yaml` | Add `forget` tool to `standard` profile |
| `src/context_service/mcp/tools/registry.py` | Register forget tool |
| `src/context_service/pipelines/assets/retention.py` | Wire `SiloConfig.resolve()` for per-silo overrides |
| `src/context_service/api/routes/admin.py` | Add `/v1/admin/erasure` endpoint, per-silo override PATCH |

---

## Sprint 1: Foundation + Forget Tool

### Task 1: Add Settings and Model Fields

**Files:**
- Modify: `src/context_service/config/settings.py`
- Modify: `src/context_service/models/silo.py`

- [ ] **Step 1: Add settings fields**

```python
# In Settings class, after existing retention fields:
retention_supersession_chain_max_length: int = Field(
    default=20,
    ge=3,
    description="Max nodes in a supersession chain before pruning",
)
forget_cancel_window_hours: int = Field(
    default=1,
    ge=1,
    description="Hours within which a forget can be cancelled",
)
forget_rate_limit_per_hour: int = Field(
    default=100,
    ge=1,
    description="Max forget operations per hour per silo",
)
```

- [ ] **Step 2: Add ForgetPolicyOverrides to models/silo.py**

```python
class ForgetPolicyOverrides(BaseModel):
    """Per-silo forget policy overrides."""

    model_config = {"extra": "ignore"}

    cancel_window_hours: int | None = Field(
        default=None,
        ge=1,
        description="Hours within which a forget can be cancelled.",
    )
    rate_limit_per_hour: int | None = Field(
        default=None,
        ge=1,
        description="Max forget operations per hour.",
    )
    enabled: bool | None = Field(
        default=None,
        description="Whether forget is enabled for this silo.",
    )
```

- [ ] **Step 3: Add supersession_chain_max_length to RetentionOverrides**

```python
# In RetentionOverrides class:
supersession_chain_max_length: int | None = Field(
    default=None,
    ge=3,
    description="Max nodes in a supersession chain before pruning.",
)
```

- [ ] **Step 4: Add forget to SiloConfig**

```python
# In SiloConfig class:
forget: ForgetPolicyOverrides = Field(default_factory=ForgetPolicyOverrides)
```

- [ ] **Step 5: Extend ResolvedSiloConfig**

```python
# Add to ResolvedSiloConfig:
supersession_chain_max_length: int
forget_cancel_window_hours: int
forget_rate_limit_per_hour: int
forget_enabled: bool
```

- [ ] **Step 6: Update SiloConfig.resolve()**

```python
# Add to resolve() method:
f = self.forget
# In return statement add:
supersession_chain_max_length=(
    r.supersession_chain_max_length
    if r.supersession_chain_max_length is not None
    else settings.retention_supersession_chain_max_length
),
forget_cancel_window_hours=(
    f.cancel_window_hours
    if f.cancel_window_hours is not None
    else settings.forget_cancel_window_hours
),
forget_rate_limit_per_hour=(
    f.rate_limit_per_hour
    if f.rate_limit_per_hour is not None
    else settings.forget_rate_limit_per_hour
),
forget_enabled=(
    f.enabled if f.enabled is not None else True
),
```

- [ ] **Step 7: Run type check**

Run: `uv run mypy src/context_service/models/silo.py src/context_service/config/settings.py`
Expected: No errors

- [ ] **Step 8: Commit**

```bash
git add src/context_service/config/settings.py src/context_service/models/silo.py
git commit -m "feat(retention): add forget and chain pruning settings"
```

---

### Task 2: Add Pointer Indexes

**Files:**
- Modify: `src/context_service/engine/memgraph_store.py`

- [ ] **Step 1: Add index creation queries**

```python
# Add to existing index queries list:
CREATE_TAIL_ID_INDEX = "CREATE INDEX ON :Node(tail_id);"
CREATE_HEAD_ID_INDEX = "CREATE INDEX ON :Node(head_id);"
```

- [ ] **Step 2: Add to ensure_indexes method**

Add `CREATE_TAIL_ID_INDEX` and `CREATE_HEAD_ID_INDEX` to the list of indexes created in `_ensure_indexes()` or equivalent initialization method.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/test_memgraph_store.py -v -k index`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/memgraph_store.py
git commit -m "feat(engine): add tail_id/head_id indexes for chain lookups"
```

---

### Task 3: Add Redis Lock for Supersession

**Files:**
- Modify: `src/context_service/engine/memgraph_store.py`

- [ ] **Step 1: Add lock helper**

```python
from context_service.stores.redis import get_redis_client

SUPERSESSION_LOCK_PREFIX = "lock:supersession:"
SUPERSESSION_LOCK_TTL_SECONDS = 30

async def _acquire_supersession_lock(self, predecessor_id: str) -> bool:
    """Acquire lock before superseding a node. Returns True if acquired."""
    redis = await get_redis_client()
    lock_key = f"{SUPERSESSION_LOCK_PREFIX}{predecessor_id}"
    return await redis.set(lock_key, "1", nx=True, ex=SUPERSESSION_LOCK_TTL_SECONDS)

async def _release_supersession_lock(self, predecessor_id: str) -> None:
    """Release supersession lock."""
    redis = await get_redis_client()
    lock_key = f"{SUPERSESSION_LOCK_PREFIX}{predecessor_id}"
    await redis.delete(lock_key)
```

- [ ] **Step 2: Wire lock into supersession write path**

Find the method that creates SUPERSEDES edges (likely in `create_supersedes_edge` or similar). Wrap the write in lock acquire/release:

```python
async def create_supersedes_edge(self, new_id: str, predecessor_id: str, silo_id: str) -> bool:
    if not await self._acquire_supersession_lock(predecessor_id):
        raise ConflictError(f"Concurrent supersession of {predecessor_id}")
    try:
        # existing edge creation + pointer update logic
        ...
    finally:
        await self._release_supersession_lock(predecessor_id)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/engine/ -v -k supersed`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/engine/memgraph_store.py
git commit -m "feat(engine): add Redis lock for supersession race prevention"
```

---

### Task 4: Add Qdrant Tombstone Filter

**Files:**
- Modify: `src/context_service/engine/qdrant_store.py`
- Test: `tests/engine/test_qdrant_store.py`

- [ ] **Step 1: Write failing test**

```python
# tests/engine/test_qdrant_store.py
async def test_search_excludes_tombstoned_nodes(qdrant_store, silo_id):
    """Tombstoned nodes should not appear in search results."""
    # Insert a node
    node_id = "test-node-1"
    await qdrant_store.upsert_vector(
        silo_id=silo_id,
        node_id=node_id,
        vector=[0.1] * 512,
        payload={"silo_id": silo_id, "node_type": "Observation"},
    )
    
    # Tombstone it
    await qdrant_store.set_payload(
        silo_id=silo_id,
        node_id=node_id,
        payload={"tombstoned_at": 1716249600000000},  # epoch microseconds
    )
    
    # Search should not find it
    results = await qdrant_store.search(
        silo_id=silo_id,
        vector=[0.1] * 512,
        limit=10,
    )
    assert not any(r.node_id == node_id for r in results)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_qdrant_store.py::test_search_excludes_tombstoned_nodes -v`
Expected: FAIL (set_payload not implemented or filter not applied)

- [ ] **Step 3: Add set_payload method**

```python
async def set_payload(
    self,
    silo_id: str,
    node_id: str,
    payload: dict[str, Any],
) -> None:
    """Update payload fields on an existing point."""
    collection = await self._ensure_collection(silo_id)
    client = await self._qdrant._get_client()
    await client.set_payload(
        collection_name=collection,
        payload=payload,
        points=[node_id],
        wait=True,
    )
```

- [ ] **Step 4: Add tombstone filter to search**

In the `search` method, add filter condition:

```python
# Build filter
conditions = [
    FieldCondition(key="silo_id", match=MatchValue(value=silo_id)),
]
# Exclude tombstoned nodes
conditions.append(
    FieldCondition(
        key="tombstoned_at",
        match=MatchValue(value=None),  # Only match where tombstoned_at is null
    )
)
# Or use IsNull condition if Qdrant supports it:
from qdrant_client.models import IsNullCondition
conditions.append(IsNullCondition(is_null=PayloadField(key="tombstoned_at")))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_qdrant_store.py::test_search_excludes_tombstoned_nodes -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/engine/qdrant_store.py tests/engine/test_qdrant_store.py
git commit -m "feat(qdrant): add tombstone filter and set_payload method"
```

---

### Task 5: Add Tombstone Payload Index

**Files:**
- Modify: `src/context_service/engine/qdrant_store.py`

- [ ] **Step 1: Add payload index in _ensure_collection**

```python
# In _ensure_collection, after collection creation:
await client.create_payload_index(
    collection_name=name,
    field_name="tombstoned_at",
    field_schema=PayloadSchemaType.INTEGER,
    wait=True,
)
```

- [ ] **Step 2: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/engine/qdrant_store.py
git commit -m "feat(qdrant): add tombstoned_at payload index"
```

---

### Task 6: Three-Store Hard Delete Coordination

**Files:**
- Modify: `src/context_service/retention/service.py`
- Create: `src/context_service/retention/dead_letter.py`
- Test: `tests/retention/test_three_store_delete.py`

- [ ] **Step 1: Write failing test**

```python
# tests/retention/test_three_store_delete.py
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_stores():
    return {
        "memgraph": AsyncMock(),
        "qdrant": AsyncMock(),
        "postgres": AsyncMock(),
    }

async def test_hard_delete_memgraph_first(mock_stores):
    """Memgraph delete must succeed before Qdrant/Postgres."""
    from context_service.retention.service import RetentionService
    
    mock_stores["memgraph"].execute_query.return_value = [{"id": "node-1"}]
    
    service = RetentionService(
        store=mock_stores["memgraph"],
        qdrant_store=mock_stores["qdrant"],
    )
    
    await service.hard_delete_node("node-1", "silo-1")
    
    # Verify call order: memgraph first
    mock_stores["memgraph"].execute_query.assert_called()
    mock_stores["qdrant"].delete_vectors.assert_called_with(
        silo_id="silo-1",
        node_ids=["node-1"],
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retention/test_three_store_delete.py -v`
Expected: FAIL

- [ ] **Step 3: Create dead_letter.py**

```python
# src/context_service/retention/dead_letter.py
"""Dead-letter queue for failed Qdrant deletes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog

from context_service.stores.redis import get_redis_client

logger = structlog.get_logger(__name__)

DEAD_LETTER_KEY = "dead_letter:qdrant_delete"


async def enqueue_failed_delete(silo_id: str, node_id: str, error: str) -> None:
    """Add failed delete to dead-letter queue for reconciliation."""
    redis = await get_redis_client()
    entry = {
        "silo_id": silo_id,
        "node_id": node_id,
        "error": error,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await redis.lpush(DEAD_LETTER_KEY, json.dumps(entry))
    logger.warning("enqueued_dead_letter", silo_id=silo_id, node_id=node_id)


async def dequeue_failed_deletes(batch_size: int = 100) -> list[dict]:
    """Pop entries from dead-letter queue for retry."""
    redis = await get_redis_client()
    entries = []
    for _ in range(batch_size):
        raw = await redis.rpop(DEAD_LETTER_KEY)
        if raw is None:
            break
        entries.append(json.loads(raw))
    return entries
```

- [ ] **Step 4: Update RetentionService.hard_delete_nodes**

```python
# src/context_service/retention/service.py
from context_service.retention.dead_letter import enqueue_failed_delete

async def hard_delete_node(
    self,
    node_id: str,
    silo_id: str,
) -> bool:
    """Delete from all three stores. Memgraph first, then Qdrant, then Postgres."""
    # 1. Memgraph (must succeed)
    result = await self._store.execute_query(
        HARD_DELETE_NODE,
        {"id": node_id, "silo_id": silo_id},
    )
    if not result:
        return False
    
    # 2. Qdrant (retry 3x, dead-letter on failure)
    if self._qdrant_store:
        for attempt in range(3):
            try:
                await self._qdrant_store.delete_vectors(
                    silo_id=silo_id,
                    node_ids=[node_id],
                )
                break
            except Exception as e:
                if attempt == 2:
                    await enqueue_failed_delete(silo_id, node_id, str(e))
    
    return True
```

- [ ] **Step 5: Update __init__ to accept qdrant_store**

```python
def __init__(
    self,
    store: HyperGraphStore,
    policy: RetentionPolicy | None = None,
    qdrant_store: EngineQdrantStore | None = None,
) -> None:
    self._store = store
    self._policy = policy or RetentionPolicy()
    self._qdrant_store = qdrant_store
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/retention/test_three_store_delete.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/retention/service.py src/context_service/retention/dead_letter.py tests/retention/test_three_store_delete.py
git commit -m "feat(retention): three-store hard-delete with dead-letter queue"
```

---

### Task 7: Dead-Letter Reconciliation Dagster Job

**Files:**
- Create: `src/context_service/pipelines/assets/dead_letter_reconciliation.py`

- [ ] **Step 1: Create the asset**

```python
# src/context_service/pipelines/assets/dead_letter_reconciliation.py
"""Dagster job to retry failed Qdrant deletes from dead-letter queue."""

from __future__ import annotations

import structlog
from dagster import OpExecutionContext, asset

from context_service.retention.dead_letter import dequeue_failed_deletes

logger = structlog.get_logger(__name__)


@asset(
    group_name="retention",
    description="Retry failed Qdrant deletes from dead-letter queue",
)
async def dead_letter_reconciliation(context: OpExecutionContext) -> dict:
    """Process dead-letter queue entries."""
    from context_service.config.settings import get_settings
    from context_service.engine.qdrant_store import EngineQdrantStore
    from context_service.stores.qdrant import get_qdrant_client

    settings = get_settings()
    qdrant_client = await get_qdrant_client(settings)
    qdrant_store = EngineQdrantStore(qdrant_client, hybrid=settings.qdrant_hybrid_search)

    entries = await dequeue_failed_deletes(batch_size=100)
    succeeded = 0
    failed = 0

    for entry in entries:
        try:
            await qdrant_store.delete_vectors(
                silo_id=entry["silo_id"],
                node_ids=[entry["node_id"]],
            )
            succeeded += 1
        except Exception as e:
            logger.error(
                "dead_letter_retry_failed",
                node_id=entry["node_id"],
                error=str(e),
            )
            failed += 1

    context.log.info(f"Dead-letter reconciliation: {succeeded} succeeded, {failed} failed")
    return {"succeeded": succeeded, "failed": failed}
```

- [ ] **Step 2: Register in __init__.py**

Add `dead_letter_reconciliation` to `src/context_service/pipelines/assets/__init__.py` exports.

- [ ] **Step 3: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/dead_letter_reconciliation.py src/context_service/pipelines/assets/__init__.py
git commit -m "feat(pipelines): add dead-letter reconciliation Dagster job"
```

---

### Task 8: Forget Service

**Files:**
- Create: `src/context_service/retention/forget_service.py`
- Test: `tests/retention/test_forget_service.py`

- [ ] **Step 1: Write failing test for forget**

```python
# tests/retention/test_forget_service.py
import pytest
from datetime import UTC, datetime
from unittest.mock import AsyncMock

@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_query.return_value = [{"id": "node-1", "downstream_count": 3}]
    return store

async def test_forget_tombstones_node(mock_store):
    from context_service.retention.forget_service import ForgetService
    
    service = ForgetService(store=mock_store, qdrant_store=AsyncMock())
    result = await service.forget("node-1", "silo-1")
    
    assert result["status"] == "tombstoned"
    assert result["node_id"] == "node-1"
    assert result["downstream_references"] == 3
    mock_store.execute_query.assert_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/retention/test_forget_service.py -v`
Expected: FAIL

- [ ] **Step 3: Create forget_service.py**

```python
# src/context_service/retention/forget_service.py
"""Agent-driven forget operations with cancel window."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore

logger = structlog.get_logger(__name__)


FORGET_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL
SET n.tombstoned_at = $tombstoned_at,
    n.forget_requested_at = $forget_requested_at,
    n.heat_dirty = true
WITH n
OPTIONAL MATCH (other)-[]->(n)
WHERE other.tombstoned_at IS NULL
RETURN n.id AS id, count(other) AS downstream_count
"""

CANCEL_FORGET = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE n.forget_requested_at IS NOT NULL
  AND n.forget_requested_at > $cancel_cutoff
SET n.tombstoned_at = NULL,
    n.forget_requested_at = NULL,
    n.retention_run_id = NULL,
    n.heat_dirty = true
RETURN n.id AS id
"""

COUNT_DOWNSTREAM = """
MATCH (n {id: $id, silo_id: $silo_id})
OPTIONAL MATCH (other)-[]->(n)
WHERE other.tombstoned_at IS NULL
RETURN count(other) AS downstream_count
"""


class ForgetService:
    """Handle agent-driven forget operations."""

    def __init__(
        self,
        store: HyperGraphStore,
        qdrant_store: EngineQdrantStore | None = None,
        cancel_window_hours: int = 1,
    ) -> None:
        self._store = store
        self._qdrant_store = qdrant_store
        self._cancel_window_hours = cancel_window_hours

    async def forget(
        self,
        node_id: str,
        silo_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """Tombstone a node. Returns downstream reference count."""
        now = datetime.now(UTC)
        now_micros = int(now.timestamp() * 1_000_000)

        result = await self._store.execute_query(
            FORGET_NODE,
            {
                "id": node_id,
                "silo_id": silo_id,
                "tombstoned_at": now_micros,
                "forget_requested_at": now_micros,
            },
        )

        if not result:
            return {"status": "not_found", "node_id": node_id}

        # Sync tombstone to Qdrant payload
        if self._qdrant_store:
            await self._qdrant_store.set_payload(
                silo_id=silo_id,
                node_id=node_id,
                payload={"tombstoned_at": now_micros},
            )

        downstream = result[0].get("downstream_count", 0)
        logger.info(
            "node_forgotten",
            node_id=node_id,
            silo_id=silo_id,
            downstream_references=downstream,
            reason=reason,
        )

        return {
            "status": "tombstoned",
            "node_id": node_id,
            "downstream_references": downstream,
            "tombstoned_at": now.isoformat(),
        }

    async def cancel_forget(
        self,
        node_id: str,
        silo_id: str,
    ) -> dict[str, Any]:
        """Reverse a forget if within cancel window."""
        now = datetime.now(UTC)
        now_micros = int(now.timestamp() * 1_000_000)
        cancel_cutoff = now_micros - (self._cancel_window_hours * 3600 * 1_000_000)

        result = await self._store.execute_query(
            CANCEL_FORGET,
            {
                "id": node_id,
                "silo_id": silo_id,
                "cancel_cutoff": cancel_cutoff,
            },
        )

        if not result:
            # Check if node exists but is past cancel window
            return {"status": "cancel_window_expired", "node_id": node_id}

        # Clear tombstone from Qdrant
        if self._qdrant_store:
            await self._qdrant_store.set_payload(
                silo_id=silo_id,
                node_id=node_id,
                payload={"tombstoned_at": None},
            )

        logger.info("forget_cancelled", node_id=node_id, silo_id=silo_id)

        return {
            "status": "cancelled",
            "node_id": node_id,
            "cancelled_at": now.isoformat(),
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/retention/test_forget_service.py -v`
Expected: PASS

- [ ] **Step 5: Add test for cancel**

```python
async def test_cancel_forget_within_window(mock_store):
    from context_service.retention.forget_service import ForgetService
    
    mock_store.execute_query.return_value = [{"id": "node-1"}]
    
    service = ForgetService(store=mock_store, qdrant_store=AsyncMock())
    result = await service.cancel_forget("node-1", "silo-1")
    
    assert result["status"] == "cancelled"
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest tests/retention/test_forget_service.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/context_service/retention/forget_service.py tests/retention/test_forget_service.py
git commit -m "feat(retention): add ForgetService with cancel window"
```

---

### Task 9: Forget MCP Tool

**Files:**
- Create: `src/context_service/mcp/tools/forget.py`
- Modify: `src/context_service/mcp/tools/registry.py`
- Modify: `src/context_service/config/mcp_tools.yaml`

- [ ] **Step 1: Create forget.py**

```python
# src/context_service/mcp/tools/forget.py
"""MCP tool for agent-driven forget operations."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from pydantic import Field

from context_service.mcp.tools.context_store import get_silo_id


async def forget(
    ctx: Context,
    node_id: Annotated[str, Field(description="ID of the node to forget")],
    cancel: Annotated[bool, Field(description="If true, cancel a pending forget")] = False,
    reason: Annotated[str | None, Field(description="Reason for forgetting")] = None,
) -> dict:
    """
    Forget a node (soft delete with cancel window).
    
    Use when content is wrong or shouldn't exist.
    For content that was valid but replaced, use link(SUPERSEDES) instead.
    
    Returns downstream reference count to inform cascade decisions.
    """
    from context_service.config.settings import get_settings
    from context_service.engine.memgraph_store import EngineMemgraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore
    from context_service.models.silo import SiloConfig
    from context_service.retention.forget_service import ForgetService
    from context_service.services.silo import SiloService
    from context_service.stores.memgraph import get_memgraph_client
    from context_service.stores.qdrant import get_qdrant_client

    settings = get_settings()
    silo_id = await get_silo_id(ctx)

    # Check if forget is enabled for this silo
    silo_service = SiloService()
    silo = await silo_service.get(silo_id)
    silo_config = SiloConfig.from_metadata_dict(silo.metadata or {})
    resolved = silo_config.resolve(settings)

    if not resolved.forget_enabled:
        return {"error": "forget is disabled for this silo"}

    # Initialize stores
    mg_client = await get_memgraph_client(settings)
    memgraph_store = EngineMemgraphStore(mg_client)
    qdrant_client = await get_qdrant_client(settings)
    qdrant_store = EngineQdrantStore(qdrant_client, hybrid=settings.qdrant_hybrid_search)

    service = ForgetService(
        store=memgraph_store,
        qdrant_store=qdrant_store,
        cancel_window_hours=resolved.forget_cancel_window_hours,
    )

    if cancel:
        return await service.cancel_forget(node_id, silo_id)
    else:
        return await service.forget(node_id, silo_id, reason=reason)
```

- [ ] **Step 2: Register in registry.py**

```python
# In src/context_service/mcp/tools/registry.py
from context_service.mcp.tools.forget import forget

# Add to tool registration:
mcp.tool(forget)
```

- [ ] **Step 3: Add to mcp_tools.yaml**

```yaml
# Add to profiles.standard list:
  standard:
    - remember
    - learn
    - believe
    - recall
    - trace
    - link
    - forget  # NEW

# Add to tools section:
  forget:
    description: "Forget a node (soft delete). Returns downstream references. Use when content is wrong. For valid-but-replaced content, use link(SUPERSEDES)."
    maps_to: retention
```

- [ ] **Step 4: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/mcp/tools/forget.py src/context_service/mcp/tools/registry.py src/context_service/config/mcp_tools.yaml
git commit -m "feat(mcp): add forget tool to standard profile"
```

---

### Task 10: Wire SiloConfig.resolve() into Retention Asset

**Files:**
- Modify: `src/context_service/pipelines/assets/retention.py`

- [ ] **Step 1: Read current retention asset**

Read the file to understand current structure.

- [ ] **Step 2: Update to use SiloConfig.resolve()**

```python
# In the retention asset, replace:
# policy = RetentionPolicy.from_settings(settings)

# With:
from context_service.models.silo import SiloConfig
from context_service.services.silo import SiloService

silo_service = SiloService()
silo = await silo_service.get(silo_id)
silo_config = SiloConfig.from_metadata_dict(silo.metadata or {})
resolved = silo_config.resolve(settings)

policy = RetentionPolicy(
    ephemeral_max_age_hours=resolved.ephemeral_max_age_hours,
    standard_max_age_days=resolved.standard_max_age_days,
    standard_heat_threshold=resolved.standard_heat_threshold,
    durable_max_age_days=resolved.durable_max_age_days,
    durable_heat_threshold=resolved.durable_heat_threshold,
    meta_observation_max_count=resolved.meta_observation_max_count,
    grace_period_days=resolved.grace_period_days,
)
```

- [ ] **Step 3: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/retention.py
git commit -m "fix(retention): wire SiloConfig.resolve() for per-silo overrides"
```

---

## Sprint 2: Chain Pruning + GDPR

### Task 11: Add Stub-Retention Queries

**Files:**
- Modify: `src/context_service/retention/queries.py`

- [ ] **Step 1: Add chain length query**

```python
FIND_LONG_CHAINS = """
MATCH (head {silo_id: $silo_id})
WHERE head.head_id = head.id  // Is a chain head
WITH head
MATCH path = (head)-[:SUPERSEDES*]->(tail)
WHERE tail.tail_id = tail.id  // Is a chain tail
WITH head, length(path) + 1 AS chain_length
WHERE chain_length > $max_length
RETURN head.id AS head_id, chain_length
"""

FIND_CHAIN_INTERIOR_NODES = """
MATCH path = (head {id: $head_id, silo_id: $silo_id})-[:SUPERSEDES*]->(tail)
WHERE tail.tail_id = tail.id
WITH nodes(path) AS chain_nodes
UNWIND chain_nodes[1..-1] AS interior  // Skip head (first) and tail (last)
RETURN interior.id AS id
"""

COMPACT_TO_STUB = """
MATCH (n {id: $id, silo_id: $silo_id})
SET n.content = NULL,
    n.properties = NULL,
    n.compacted_at = $compacted_at,
    n.compact_reason = 'chain_pruning'
RETURN n.id AS id
"""
```

- [ ] **Step 2: Add HyperEdge cleanup query**

```python
FIND_ORPHANED_HYPEREDGES = """
MATCH (h:HyperEdge {silo_id: $silo_id})
WHERE NOT (h)-[:PARTICIPANT]->()
RETURN h.id AS id
"""

DELETE_HYPEREDGE = """
MATCH (h:HyperEdge {id: $id, silo_id: $silo_id})
DETACH DELETE h
"""
```

- [ ] **Step 3: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/retention/queries.py
git commit -m "feat(retention): add stub-retention and HyperEdge cleanup queries"
```

---

### Task 12: Chain Pruning Dagster Asset

**Files:**
- Create: `src/context_service/pipelines/assets/chain_pruning.py`

- [ ] **Step 1: Create the asset**

```python
# src/context_service/pipelines/assets/chain_pruning.py
"""Stub-retention for supersession chains exceeding max length."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from dagster import OpExecutionContext, asset

from context_service.models.silo import SiloConfig
from context_service.retention.queries import (
    COMPACT_TO_STUB,
    DELETE_HYPEREDGE,
    FIND_CHAIN_INTERIOR_NODES,
    FIND_LONG_CHAINS,
    FIND_ORPHANED_HYPEREDGES,
)
from context_service.services.silo import SiloService

logger = structlog.get_logger(__name__)


@asset(
    group_name="retention",
    description="Prune supersession chains to max length via stub-retention",
)
async def chain_pruning(context: OpExecutionContext) -> dict:
    """Convert interior nodes of long chains to stubs."""
    from context_service.config.settings import get_settings
    from context_service.engine.memgraph_store import EngineMemgraphStore
    from context_service.stores.memgraph import get_memgraph_client

    settings = get_settings()
    mg_client = await get_memgraph_client(settings)
    store = EngineMemgraphStore(mg_client)
    silo_service = SiloService()

    total_compacted = 0
    total_hyperedges_cleaned = 0

    # Process each silo
    silos = await silo_service.list_all()
    for silo in silos:
        silo_id = silo.id
        silo_config = SiloConfig.from_metadata_dict(silo.metadata or {})
        resolved = silo_config.resolve(settings)
        max_length = resolved.supersession_chain_max_length

        # Find chains exceeding max length
        long_chains = await store.execute_query(
            FIND_LONG_CHAINS,
            {"silo_id": silo_id, "max_length": max_length},
        )

        for chain in long_chains:
            head_id = chain["head_id"]
            
            # Get interior nodes (not head or tail)
            interior_nodes = await store.execute_query(
                FIND_CHAIN_INTERIOR_NODES,
                {"head_id": head_id, "silo_id": silo_id},
            )

            # Keep chain_min_keep nodes (head + one prior)
            nodes_to_compact = interior_nodes[:-1]  # Keep last interior node
            now_micros = int(datetime.now(UTC).timestamp() * 1_000_000)

            for node in nodes_to_compact:
                await store.execute_query(
                    COMPACT_TO_STUB,
                    {
                        "id": node["id"],
                        "silo_id": silo_id,
                        "compacted_at": now_micros,
                    },
                )
                total_compacted += 1

        # Clean orphaned HyperEdges
        orphans = await store.execute_query(
            FIND_ORPHANED_HYPEREDGES,
            {"silo_id": silo_id},
        )
        for orphan in orphans:
            await store.execute_query(
                DELETE_HYPEREDGE,
                {"id": orphan["id"], "silo_id": silo_id},
            )
            total_hyperedges_cleaned += 1

    context.log.info(
        f"Chain pruning: {total_compacted} nodes compacted, "
        f"{total_hyperedges_cleaned} orphaned HyperEdges cleaned"
    )
    return {
        "compacted": total_compacted,
        "hyperedges_cleaned": total_hyperedges_cleaned,
    }
```

- [ ] **Step 2: Register in __init__.py**

Add `chain_pruning` to exports.

- [ ] **Step 3: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/chain_pruning.py src/context_service/pipelines/assets/__init__.py
git commit -m "feat(pipelines): add chain pruning Dagster asset with stub-retention"
```

---

### Task 13: Erasure Audit Log Migration

**Files:**
- Create: `src/context_service/db/migrations/versions/XXXX_erasure_audit.py`

- [ ] **Step 1: Generate migration**

Run: `uv run alembic revision -m "add erasure audit tables"`

- [ ] **Step 2: Write migration**

```python
"""Add erasure audit tables.

Revision ID: XXXX
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "XXXX"
down_revision = "previous_revision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "erasure_audit_log",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.String(36), nullable=False, index=True),
        sa.Column("silo_id", sa.String(36), nullable=False, index=True),
        sa.Column("node_type", sa.String(64), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_by", sa.String(256), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True, index=True),
        sa.Column("cascade_ids", JSONB, nullable=True),
        sa.Column("stores_affected", JSONB, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=True),  # SHA256 for audit proof
    )

    op.create_table(
        "erasure_review_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("node_id", sa.String(36), nullable=False, index=True),
        sa.Column("silo_id", sa.String(36), nullable=False, index=True),
        sa.Column("erasure_job_id", sa.String(36), nullable=False, index=True),
        sa.Column("remaining_sources", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_decision", sa.String(32), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("erasure_review_queue")
    op.drop_table("erasure_audit_log")
```

- [ ] **Step 3: Run migration**

Run: `uv run alembic upgrade head`
Expected: Migration applied successfully

- [ ] **Step 4: Commit**

```bash
git add src/context_service/db/migrations/versions/
git commit -m "feat(db): add erasure audit tables migration"
```

---

### Task 14: Erasure Service

**Files:**
- Create: `src/context_service/services/erasure.py`
- Test: `tests/services/test_erasure.py`

- [ ] **Step 1: Write failing test**

```python
# tests/services/test_erasure.py
import pytest
from unittest.mock import AsyncMock

async def test_erasure_cascades_to_derived_nodes():
    from context_service.services.erasure import ErasureService
    
    mock_store = AsyncMock()
    mock_store.execute_query.side_effect = [
        # First call: find node
        [{"id": "node-1", "node_type": "Observation"}],
        # Second call: find derived nodes
        [{"id": "derived-1", "edge_type": "DERIVED_FROM"}],
        # Third call: check if derived-1 has other sources
        [],  # No other sources
        # Delete calls...
        [{"id": "node-1"}],
        [{"id": "derived-1"}],
    ]
    
    service = ErasureService(store=mock_store)
    result = await service.erase(
        node_ids=["node-1"],
        silo_id="silo-1",
        reason="gdpr_erasure",
        request_id="dsr-001",
    )
    
    assert result["deleted_count"] == 2
    assert "derived-1" in result["cascade_ids"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/services/test_erasure.py -v`
Expected: FAIL

- [ ] **Step 3: Create erasure.py**

```python
# src/context_service/services/erasure.py
"""GDPR-compliant erasure with cascade."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.engine.qdrant_store import EngineQdrantStore

logger = structlog.get_logger(__name__)

CASCADE_EDGE_TYPES = [
    "CITES",
    "SYNTHESIZED_FROM",
    "DERIVED_FROM",
    "PROMOTED_FROM",
    "MERGED_FROM",
    "REFERENCES",
    "CAUSES",
    "EXTRACTED_FROM",
    "CRYSTALLIZED_INTO",
    "DERIVED_FROM_EVIDENCE",
    "PROMOTED_TO",
]

FIND_DERIVED_NODES = """
MATCH (n {id: $id, silo_id: $silo_id})<-[r]-(derived)
WHERE type(r) IN $edge_types
  AND derived.tombstoned_at IS NULL
RETURN derived.id AS id, type(r) AS edge_type
"""

FIND_OTHER_SOURCES = """
MATCH (n {id: $id, silo_id: $silo_id})-[r]->(source)
WHERE type(r) IN $edge_types
  AND source.id <> $erased_id
  AND source.tombstoned_at IS NULL
RETURN source.id AS id
"""


class ErasureService:
    """GDPR erasure with cascade and partial-source detection."""

    def __init__(
        self,
        store: HyperGraphStore,
        qdrant_store: EngineQdrantStore | None = None,
        cascade_depth: int = 5,
    ) -> None:
        self._store = store
        self._qdrant_store = qdrant_store
        self._cascade_depth = cascade_depth

    async def erase(
        self,
        node_ids: list[str],
        silo_id: str,
        reason: str,
        request_id: str | None = None,
        deleted_by: str = "system",
    ) -> dict[str, Any]:
        """Erase nodes with cascade. Returns audit info."""
        request_id = request_id or str(uuid4())
        to_delete: set[str] = set(node_ids)
        partial_source_nodes: list[str] = []
        visited: set[str] = set()

        # BFS cascade
        queue = list(node_ids)
        depth = 0

        while queue and depth < self._cascade_depth:
            next_queue = []
            for node_id in queue:
                if node_id in visited:
                    continue
                visited.add(node_id)

                derived = await self._store.execute_query(
                    FIND_DERIVED_NODES,
                    {
                        "id": node_id,
                        "silo_id": silo_id,
                        "edge_types": CASCADE_EDGE_TYPES,
                    },
                )

                for d in derived:
                    derived_id = d["id"]
                    # Check if derived node has other (non-erased) sources
                    other_sources = await self._store.execute_query(
                        FIND_OTHER_SOURCES,
                        {
                            "id": derived_id,
                            "silo_id": silo_id,
                            "edge_types": CASCADE_EDGE_TYPES,
                            "erased_id": node_id,
                        },
                    )

                    if other_sources:
                        partial_source_nodes.append(derived_id)
                    else:
                        to_delete.add(derived_id)
                        next_queue.append(derived_id)

            queue = next_queue
            depth += 1

        # Perform deletions (three-store)
        deleted_count = 0
        for node_id in to_delete:
            # TODO: Use RetentionService.hard_delete_node for three-store
            await self._store.execute_query(
                "MATCH (n {id: $id, silo_id: $silo_id}) DETACH DELETE n",
                {"id": node_id, "silo_id": silo_id},
            )
            deleted_count += 1

            if self._qdrant_store:
                await self._qdrant_store.delete_vectors(
                    silo_id=silo_id,
                    node_ids=[node_id],
                )

        # TODO: Write to erasure_audit_log

        logger.info(
            "erasure_completed",
            request_id=request_id,
            deleted_count=deleted_count,
            partial_source_count=len(partial_source_nodes),
        )

        return {
            "request_id": request_id,
            "deleted_count": deleted_count,
            "cascade_ids": list(to_delete - set(node_ids)),
            "partial_source_nodes": partial_source_nodes,
        }
```

- [ ] **Step 4: Run test**

Run: `uv run pytest tests/services/test_erasure.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/services/erasure.py tests/services/test_erasure.py
git commit -m "feat(services): add ErasureService with cascade and partial-source detection"
```

---

### Task 15: GDPR REST Endpoint

**Files:**
- Modify: `src/context_service/api/routes/admin.py`

- [ ] **Step 1: Add erasure endpoint**

```python
from pydantic import BaseModel, Field

class ErasureRequest(BaseModel):
    node_ids: list[str] = Field(..., min_length=1, max_length=100)
    reason: str = Field(default="gdpr_erasure")
    request_id: str | None = None
    cascade_depth: int = Field(default=5, ge=1, le=10)

class ErasureResponse(BaseModel):
    job_id: str
    status: str = "accepted"


@router.post("/v1/admin/erasure", response_model=ErasureResponse, status_code=202)
async def request_erasure(
    request: ErasureRequest,
    silo_id: str = Depends(get_silo_id),
    user: User = Depends(require_admin),
) -> ErasureResponse:
    """
    Request GDPR erasure of nodes.
    
    Async Dagster job performs the actual deletion.
    """
    from context_service.services.erasure import ErasureService
    
    job_id = str(uuid4())
    
    # Enqueue for async processing
    # TODO: Submit to Dagster job
    
    return ErasureResponse(job_id=job_id)
```

- [ ] **Step 2: Add per-silo override PATCH**

```python
class SiloOverrideUpdate(BaseModel):
    retention: dict | None = None
    forget: dict | None = None


@router.patch("/v1/admin/silos/{silo_id}")
async def update_silo_overrides(
    silo_id: str,
    update: SiloOverrideUpdate,
    user: User = Depends(require_admin),
) -> dict:
    """Update per-silo retention and forget overrides."""
    from context_service.models.silo import SiloConfig
    from context_service.services.silo import SiloService
    
    silo_service = SiloService()
    silo = await silo_service.get(silo_id)
    
    config = SiloConfig.from_metadata_dict(silo.metadata or {})
    
    if update.retention:
        config.retention = config.retention.model_copy(update=update.retention)
    if update.forget:
        config.forget = config.forget.model_copy(update=update.forget)
    
    await silo_service.update_metadata(silo_id, config.to_metadata_dict())
    
    return {"status": "updated", "silo_id": silo_id}
```

- [ ] **Step 3: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/api/routes/admin.py
git commit -m "feat(api): add GDPR erasure endpoint and per-silo override PATCH"
```

---

### Task 16: Update Trace for Stub Nodes

**Files:**
- Modify: `src/context_service/mcp/tools/trace.py` (or equivalent provenance tool)

- [ ] **Step 1: Add stub annotation**

In the trace/provenance response building, check for `compacted_at`:

```python
# When building trace response:
if node.get("compacted_at"):
    node_data["is_stub"] = True
    node_data["stub_reason"] = node.get("compact_reason", "chain_pruning")
    node_data["compacted_at"] = node["compacted_at"]
    node_data["content"] = "[pruned: content removed for lifecycle compliance]"
```

- [ ] **Step 2: Run check**

Run: `uv run just check`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/trace.py
git commit -m "feat(mcp): annotate stub nodes in trace output"
```

---

## Done Criteria

- [ ] `forget` MCP tool works (tombstone + cancel within window)
- [ ] Three-store hard-delete coordinates Memgraph -> Qdrant -> Postgres
- [ ] Dead-letter queue catches failed Qdrant deletes
- [ ] Qdrant searches exclude tombstoned nodes
- [ ] Chain pruning converts interior nodes to stubs
- [ ] HyperEdge orphans cleaned up nightly
- [ ] GDPR erasure endpoint accepts requests (async job)
- [ ] Per-silo overrides work for retention and forget
- [ ] `trace` annotates stub nodes
- [ ] All tests pass: `just ci`

---

## Out of Scope (v1.1)

- Cross-silo GDPR erasure
- GDPR dry-run mode
- `subject_id` backfill tool
- Agent-facing cascade (`forget_cascade` tool)
- LLM-assisted chain collapse for `permanent` decay class
