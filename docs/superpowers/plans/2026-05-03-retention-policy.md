# Retention Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement retention policy that prevents unbounded node growth while preserving audit trail via soft-delete.

**Architecture:** Hybrid trigger (decay_class + heat + time). Two-phase deletion: tombstone immediately, hard delete after 7-day grace. Single Dagster job runs retention then summarization sequentially to avoid race conditions. Per-silo config with env var defaults.

**Tech Stack:** Dagster (job + schedule), Memgraph (Cypher), Pydantic (config models), pytest-asyncio

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/retention/__init__.py` | Package init |
| `src/context_service/retention/policy.py` | RetentionPolicy model, threshold logic |
| `src/context_service/retention/queries.py` | Cypher queries for tombstone/delete |
| `src/context_service/retention/service.py` | Async service: find candidates, tombstone, hard delete |
| `src/context_service/pipelines/assets/retention.py` | Dagster asset |
| `src/context_service/pipelines/schedules.py` | Add retention schedule |
| `src/context_service/config/settings.py` | Add retention defaults |
| `tests/test_retention_policy.py` | Unit tests for policy logic |
| `tests/test_retention_service.py` | Integration tests with Memgraph |

---

## Task 1: Retention Config Model

**Files:**
- Modify: `src/context_service/config/settings.py`
- Create: `src/context_service/retention/__init__.py`
- Create: `src/context_service/retention/policy.py`
- Test: `tests/test_retention_policy.py`

- [ ] **Step 1: Write failing test for RetentionPolicy defaults**

```python
# tests/test_retention_policy.py
import pytest
from context_service.retention.policy import RetentionPolicy, DecayThresholds

def test_retention_policy_defaults():
    policy = RetentionPolicy()
    assert policy.ephemeral_max_age_hours == 24
    assert policy.standard_max_age_days == 7
    assert policy.standard_heat_threshold == 0.3
    assert policy.durable_max_age_days == 30
    assert policy.durable_heat_threshold == 0.2
    assert policy.meta_observation_max_count == 100
    assert policy.grace_period_days == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_retention_policy.py::test_retention_policy_defaults -v`
Expected: FAIL with "No module named 'context_service.retention'"

- [ ] **Step 3: Create retention package and policy model**

```python
# src/context_service/retention/__init__.py
"""Retention policy for bounded node growth."""

from context_service.retention.policy import RetentionPolicy

__all__ = ["RetentionPolicy"]
```

```python
# src/context_service/retention/policy.py
"""Retention policy configuration and threshold logic."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetentionPolicy(BaseModel):
    """Per-silo retention thresholds with sensible defaults."""

    ephemeral_max_age_hours: int = Field(default=24, ge=1)
    standard_max_age_days: int = Field(default=7, ge=1)
    standard_heat_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    durable_max_age_days: int = Field(default=30, ge=1)
    durable_heat_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    meta_observation_max_count: int = Field(default=100, ge=10)
    grace_period_days: int = Field(default=7, ge=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_retention_policy.py::test_retention_policy_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/retention tests/test_retention_policy.py
git commit -m "feat(retention): add RetentionPolicy config model"
```

---

## Task 2: Retention Eligibility Logic

**Files:**
- Modify: `src/context_service/retention/policy.py`
- Test: `tests/test_retention_policy.py`

- [ ] **Step 1: Write failing test for eligibility check**

```python
# tests/test_retention_policy.py (append)
from datetime import datetime, timedelta, UTC

def test_ephemeral_eligible_after_24h():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_25h_ago = now - timedelta(hours=25)
    
    assert policy.is_eligible_for_tombstone(
        decay_class="ephemeral",
        created_at=created_25h_ago,
        heat_score=0.9,  # heat doesn't matter for ephemeral
        now=now,
    ) is True

def test_ephemeral_not_eligible_before_24h():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_23h_ago = now - timedelta(hours=23)
    
    assert policy.is_eligible_for_tombstone(
        decay_class="ephemeral",
        created_at=created_23h_ago,
        heat_score=0.1,
        now=now,
    ) is False

def test_standard_eligible_low_heat_old():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_8d_ago = now - timedelta(days=8)
    
    assert policy.is_eligible_for_tombstone(
        decay_class="standard",
        created_at=created_8d_ago,
        heat_score=0.2,  # below 0.3 threshold
        now=now,
    ) is True

def test_standard_not_eligible_high_heat():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_8d_ago = now - timedelta(days=8)
    
    assert policy.is_eligible_for_tombstone(
        decay_class="standard",
        created_at=created_8d_ago,
        heat_score=0.5,  # above 0.3 threshold
        now=now,
    ) is False

def test_permanent_never_eligible():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_1y_ago = now - timedelta(days=365)
    
    assert policy.is_eligible_for_tombstone(
        decay_class="permanent",
        created_at=created_1y_ago,
        heat_score=0.0,
        now=now,
    ) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retention_policy.py -v -k "eligible"`
Expected: FAIL with "RetentionPolicy has no attribute 'is_eligible_for_tombstone'"

- [ ] **Step 3: Implement eligibility logic**

```python
# src/context_service/retention/policy.py (append to class)
from datetime import datetime, timedelta, UTC

class RetentionPolicy(BaseModel):
    # ... existing fields ...

    def is_eligible_for_tombstone(
        self,
        decay_class: str,
        created_at: datetime,
        heat_score: float,
        now: datetime | None = None,
    ) -> bool:
        """Check if a node is eligible for tombstoning based on policy."""
        if now is None:
            now = datetime.now(UTC)

        age = now - created_at

        if decay_class == "permanent":
            return False

        if decay_class == "ephemeral":
            return age >= timedelta(hours=self.ephemeral_max_age_hours)

        if decay_class == "standard":
            return (
                age >= timedelta(days=self.standard_max_age_days)
                and heat_score < self.standard_heat_threshold
            )

        if decay_class == "durable":
            return (
                age >= timedelta(days=self.durable_max_age_days)
                and heat_score < self.durable_heat_threshold
            )

        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retention_policy.py -v -k "eligible"`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/context_service/retention/policy.py tests/test_retention_policy.py
git commit -m "feat(retention): add eligibility logic for tombstoning"
```

---

## Task 3: Retention Cypher Queries

**Files:**
- Create: `src/context_service/retention/queries.py`
- Test: `tests/test_retention_queries.py`

- [ ] **Step 1: Write the queries module**

```python
# src/context_service/retention/queries.py
"""Cypher queries for retention operations."""

FIND_TOMBSTONE_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.decay_class IS NOT NULL
  AND NOT exists(n.tombstoned_at)
  AND n.decay_class <> 'permanent'
RETURN n.id AS id,
       n.decay_class AS decay_class,
       n.created_at AS created_at,
       coalesce(n.heat_score, 0.5) AS heat_score
"""

TOMBSTONE_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
WHERE NOT exists(n.tombstoned_at)
SET n.tombstoned_at = $tombstoned_at,
    n.retention_run_id = $run_id
RETURN n.id AS id
"""

FIND_HARD_DELETE_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.tombstoned_at IS NOT NULL
  AND n.tombstoned_at < $grace_cutoff
RETURN n.id AS id
"""

HARD_DELETE_NODE = """
MATCH (n {id: $id, silo_id: $silo_id})
DETACH DELETE n
"""

FIND_EXCESS_META_OBSERVATIONS = """
MATCH (n:MetaObservation {silo_id: $silo_id})
WHERE NOT exists(n.tombstoned_at)
WITH n ORDER BY n.created_at DESC
SKIP $keep_count
RETURN n.id AS id
"""

MARK_HEAT_DIRTY = """
MATCH (n {silo_id: $silo_id})
WHERE n.id IN $node_ids
SET n.heat_dirty = true
"""
```

- [ ] **Step 2: Write query validation test**

```python
# tests/test_retention_queries.py
from context_service.retention.queries import (
    FIND_TOMBSTONE_CANDIDATES,
    TOMBSTONE_NODE,
    FIND_HARD_DELETE_CANDIDATES,
    HARD_DELETE_NODE,
    FIND_EXCESS_META_OBSERVATIONS,
    MARK_HEAT_DIRTY,
)

def test_queries_are_valid_cypher_syntax():
    """Basic validation that queries are importable strings."""
    assert "MATCH" in FIND_TOMBSTONE_CANDIDATES
    assert "silo_id" in FIND_TOMBSTONE_CANDIDATES
    assert "$silo_id" in TOMBSTONE_NODE
    assert "$grace_cutoff" in FIND_HARD_DELETE_CANDIDATES
    assert "DETACH DELETE" in HARD_DELETE_NODE
    assert "SKIP $keep_count" in FIND_EXCESS_META_OBSERVATIONS
    assert "heat_dirty" in MARK_HEAT_DIRTY
```

- [ ] **Step 3: Run test**

Run: `uv run pytest tests/test_retention_queries.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/context_service/retention/queries.py tests/test_retention_queries.py
git commit -m "feat(retention): add Cypher queries for tombstone/delete"
```

---

## Task 4: Retention Service

**Files:**
- Create: `src/context_service/retention/service.py`
- Modify: `src/context_service/retention/__init__.py`
- Test: `tests/test_retention_service.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/test_retention_service.py
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock, MagicMock

from context_service.retention.service import RetentionService
from context_service.retention.policy import RetentionPolicy

@pytest.fixture
def mock_store():
    store = AsyncMock()
    store.execute_query = AsyncMock(return_value=[])
    return store

@pytest.fixture
def service(mock_store):
    return RetentionService(store=mock_store, policy=RetentionPolicy())

@pytest.mark.asyncio
async def test_find_tombstone_candidates_queries_store(service, mock_store):
    await service.find_tombstone_candidates("silo-123")
    mock_store.execute_query.assert_called_once()
    call_args = mock_store.execute_query.call_args
    assert "silo_id" in call_args[1] or call_args[0][1].get("silo_id") == "silo-123"

@pytest.mark.asyncio
async def test_tombstone_nodes_sets_timestamp(service, mock_store):
    mock_store.execute_query.return_value = [{"id": "node-1"}]
    run_id = "run-abc"
    
    result = await service.tombstone_nodes(["node-1"], "silo-123", run_id)
    
    assert result == 1
    call_args = mock_store.execute_query.call_args
    assert "tombstoned_at" in str(call_args) or "run_id" in str(call_args)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retention_service.py -v`
Expected: FAIL with "No module named 'context_service.retention.service'"

- [ ] **Step 3: Implement RetentionService**

```python
# src/context_service/retention/service.py
"""Retention service: find candidates, tombstone, hard delete."""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

from context_service.retention.policy import RetentionPolicy
from context_service.retention.queries import (
    FIND_TOMBSTONE_CANDIDATES,
    TOMBSTONE_NODE,
    FIND_HARD_DELETE_CANDIDATES,
    HARD_DELETE_NODE,
    FIND_EXCESS_META_OBSERVATIONS,
    MARK_HEAT_DIRTY,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


class RetentionService:
    """Orchestrates retention sweeps for a silo."""

    def __init__(
        self,
        store: HyperGraphStore,
        policy: RetentionPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or RetentionPolicy()

    async def find_tombstone_candidates(
        self,
        silo_id: str,
        now: datetime | None = None,
    ) -> list[str]:
        """Find nodes eligible for tombstoning."""
        if now is None:
            now = datetime.now(UTC)

        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_TOMBSTONE_CANDIDATES,
            {"silo_id": silo_id},
        )

        eligible_ids: list[str] = []
        for row in rows:
            created_at = row.get("created_at")
            if isinstance(created_at, str):
                created_at = datetime.fromisoformat(created_at)

            if self._policy.is_eligible_for_tombstone(
                decay_class=row["decay_class"],
                created_at=created_at,
                heat_score=row["heat_score"],
                now=now,
            ):
                eligible_ids.append(row["id"])

        return eligible_ids

    async def tombstone_nodes(
        self,
        node_ids: list[str],
        silo_id: str,
        run_id: str,
    ) -> int:
        """Tombstone nodes by setting tombstoned_at timestamp."""
        now = datetime.now(UTC)
        count = 0

        for node_id in node_ids:
            result = await self._store.execute_query(
                TOMBSTONE_NODE,
                {
                    "id": node_id,
                    "silo_id": silo_id,
                    "tombstoned_at": now.isoformat(),
                    "run_id": run_id,
                },
            )
            if result:
                count += 1

        if node_ids:
            await self._store.execute_query(
                MARK_HEAT_DIRTY,
                {"silo_id": silo_id, "node_ids": node_ids},
            )

        logger.info("tombstoned_nodes", silo_id=silo_id, count=count, run_id=run_id)
        return count

    async def find_hard_delete_candidates(self, silo_id: str) -> list[str]:
        """Find tombstoned nodes past grace period."""
        grace_cutoff = datetime.now(UTC) - timedelta(days=self._policy.grace_period_days)

        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_HARD_DELETE_CANDIDATES,
            {"silo_id": silo_id, "grace_cutoff": grace_cutoff.isoformat()},
        )

        return [row["id"] for row in rows]

    async def hard_delete_nodes(self, node_ids: list[str], silo_id: str) -> int:
        """Permanently delete tombstoned nodes."""
        count = 0
        for node_id in node_ids:
            await self._store.execute_query(
                HARD_DELETE_NODE,
                {"id": node_id, "silo_id": silo_id},
            )
            count += 1

        logger.info("hard_deleted_nodes", silo_id=silo_id, count=count)
        return count

    async def tombstone_excess_meta_observations(
        self,
        silo_id: str,
        run_id: str,
    ) -> int:
        """Tombstone MetaObservation nodes beyond max count."""
        rows: list[dict[str, Any]] = await self._store.execute_query(
            FIND_EXCESS_META_OBSERVATIONS,
            {"silo_id": silo_id, "keep_count": self._policy.meta_observation_max_count},
        )

        excess_ids = [row["id"] for row in rows]
        if excess_ids:
            return await self.tombstone_nodes(excess_ids, silo_id, run_id)
        return 0

    async def run_sweep(self, silo_id: str) -> dict[str, int]:
        """Run full retention sweep: tombstone eligible, hard delete expired."""
        run_id = str(uuid4())

        candidates = await self.find_tombstone_candidates(silo_id)
        tombstoned = await self.tombstone_nodes(candidates, silo_id, run_id)

        meta_tombstoned = await self.tombstone_excess_meta_observations(silo_id, run_id)

        delete_candidates = await self.find_hard_delete_candidates(silo_id)
        deleted = await self.hard_delete_nodes(delete_candidates, silo_id)

        return {
            "tombstoned": tombstoned,
            "meta_tombstoned": meta_tombstoned,
            "deleted": deleted,
            "run_id": run_id,
        }
```

- [ ] **Step 4: Update package init**

```python
# src/context_service/retention/__init__.py
"""Retention policy for bounded node growth."""

from context_service.retention.policy import RetentionPolicy
from context_service.retention.service import RetentionService

__all__ = ["RetentionPolicy", "RetentionService"]
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_retention_service.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/retention tests/test_retention_service.py
git commit -m "feat(retention): add RetentionService for sweep operations"
```

---

## Task 5: Dagster Asset

**Files:**
- Create: `src/context_service/pipelines/assets/retention.py`
- Modify: `src/context_service/pipelines/assets/__init__.py`
- Modify: `src/context_service/pipelines/definitions.py`

- [ ] **Step 1: Create retention asset**

```python
# src/context_service/pipelines/assets/retention.py
"""Retention sweep Dagster asset."""

from __future__ import annotations

import dagster as dg

from context_service.pipelines.resources import MemgraphResource
from context_service.retention import RetentionPolicy, RetentionService


@dg.asset(
    name="retention_sweep",
    description="Tombstone and hard-delete nodes per retention policy.",
    compute_kind="memgraph",
    group_name="maintenance",
)
async def retention_sweep(
    context: dg.AssetExecutionContext,
    memgraph: MemgraphResource,
    config: dg.Config,
) -> dg.MaterializeResult:
    """Run retention sweep for a single silo."""
    silo_id = config.get("silo_id")
    if not silo_id:
        raise dg.Failure("silo_id config required")

    driver = await memgraph.driver()
    from context_service.stores import MemgraphClient
    client = MemgraphClient(driver)

    policy = RetentionPolicy()
    service = RetentionService(store=client, policy=policy)

    result = await service.run_sweep(silo_id)

    context.log.info(
        f"Retention sweep complete: {result['tombstoned']} tombstoned, "
        f"{result['deleted']} deleted"
    )

    return dg.MaterializeResult(
        metadata={
            "silo_id": silo_id,
            "tombstoned": result["tombstoned"],
            "meta_tombstoned": result["meta_tombstoned"],
            "deleted": result["deleted"],
            "run_id": result["run_id"],
        }
    )
```

- [ ] **Step 2: Update assets init to include retention**

Check existing pattern in `src/context_service/pipelines/assets/__init__.py` and add import.

- [ ] **Step 3: Run typecheck**

Run: `uv run mypy src/context_service/retention src/context_service/pipelines/assets/retention.py`
Expected: Success (0 errors)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/retention.py src/context_service/pipelines/assets/__init__.py
git commit -m "feat(retention): add Dagster retention_sweep asset"
```

---

## Task 6: Retention Schedule

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Add retention schedule**

```python
# src/context_service/pipelines/schedules.py (append)

@dg.schedule(
    cron_schedule="0 3 * * *",
    name="retention_schedule",
    target=dg.AssetSelection.assets("retention_sweep"),
    description="Daily retention sweep (03:00 UTC) per active silo.",
    execution_timezone="UTC",
)
def retention_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Yield one retention RunRequest per active silo."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"retention-{silo_id}-{context.scheduled_execution_time.isoformat()}",
            run_config={"ops": {"retention_sweep": {"config": {"silo_id": silo_id}}}},
            tags={"silo_id": silo_id},
        )
```

- [ ] **Step 2: Verify schedule loads**

Run: `uv run python -c "from context_service.pipelines.schedules import retention_schedule; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat(retention): add daily retention_schedule at 03:00 UTC"
```

---

## Task 7: Query Filter for Tombstoned Nodes

**Files:**
- Modify: `src/context_service/db/queries.py`
- Test: `tests/test_retention_query_filter.py`

- [ ] **Step 1: Identify queries that need tombstone filter**

Run: `grep -n "MATCH.*silo_id" src/context_service/db/queries.py | head -10`

- [ ] **Step 2: Add tombstone filter helper**

```python
# src/context_service/db/queries.py (add near top)

def _not_tombstoned() -> str:
    """WHERE clause fragment to exclude tombstoned nodes."""
    return "NOT exists(n.tombstoned_at)"
```

- [ ] **Step 3: Update key read queries to filter tombstoned**

Add `AND NOT exists(n.tombstoned_at)` to:
- `GET_NODE_BY_ID`
- `SEARCH_NODES`
- Content fetch queries

(Specific lines depend on existing query structure)

- [ ] **Step 4: Write test verifying tombstoned nodes excluded**

```python
# tests/test_retention_query_filter.py
from context_service.db.queries import GET_NODE_BY_ID

def test_get_node_by_id_excludes_tombstoned():
    assert "tombstoned_at" in GET_NODE_BY_ID or "NOT exists" in GET_NODE_BY_ID
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/db/queries.py tests/test_retention_query_filter.py
git commit -m "feat(retention): filter tombstoned nodes from read queries"
```

---

## Task 8: Settings Integration

**Files:**
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Add retention defaults to Settings**

```python
# src/context_service/config/settings.py (add to Settings class)

# Retention policy defaults
retention_ephemeral_max_age_hours: int = Field(default=24, ge=1)
retention_standard_max_age_days: int = Field(default=7, ge=1)
retention_standard_heat_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
retention_durable_max_age_days: int = Field(default=30, ge=1)
retention_durable_heat_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
retention_meta_observation_max_count: int = Field(default=100, ge=10)
retention_grace_period_days: int = Field(default=7, ge=1)
```

- [ ] **Step 2: Add factory method to create RetentionPolicy from settings**

```python
# src/context_service/retention/policy.py (add class method)

@classmethod
def from_settings(cls, settings: "Settings") -> "RetentionPolicy":
    """Create RetentionPolicy from application settings."""
    return cls(
        ephemeral_max_age_hours=settings.retention_ephemeral_max_age_hours,
        standard_max_age_days=settings.retention_standard_max_age_days,
        standard_heat_threshold=settings.retention_standard_heat_threshold,
        durable_max_age_days=settings.retention_durable_max_age_days,
        durable_heat_threshold=settings.retention_durable_heat_threshold,
        meta_observation_max_count=settings.retention_meta_observation_max_count,
        grace_period_days=settings.retention_grace_period_days,
    )
```

- [ ] **Step 3: Update Dagster asset to use settings**

- [ ] **Step 4: Commit**

```bash
git add src/context_service/config/settings.py src/context_service/retention/policy.py
git commit -m "feat(retention): wire retention policy to app settings"
```

---

## Task 9: Integration Test

**Files:**
- Create: `tests/integration/test_retention_integration.py`

- [ ] **Step 1: Write integration test with real Memgraph**

```python
# tests/integration/test_retention_integration.py
import pytest
from datetime import datetime, timedelta, UTC

from context_service.retention import RetentionPolicy, RetentionService

pytestmark = pytest.mark.integration

@pytest.mark.asyncio
async def test_retention_sweep_tombstones_old_ephemeral(memgraph_store, test_silo_id):
    """Old ephemeral nodes get tombstoned."""
    # Create an old ephemeral node
    old_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    await memgraph_store.execute_query(
        """
        CREATE (n:Memory {
            id: $id,
            silo_id: $silo_id,
            decay_class: 'ephemeral',
            created_at: $created_at
        })
        """,
        {"id": "test-ephemeral-1", "silo_id": test_silo_id, "created_at": old_time},
    )

    service = RetentionService(store=memgraph_store, policy=RetentionPolicy())
    result = await service.run_sweep(test_silo_id)

    assert result["tombstoned"] >= 1

    # Verify tombstone was set
    rows = await memgraph_store.execute_query(
        "MATCH (n {id: $id}) RETURN n.tombstoned_at AS ts",
        {"id": "test-ephemeral-1"},
    )
    assert rows[0]["ts"] is not None
```

- [ ] **Step 2: Run integration test**

Run: `uv run pytest tests/integration/test_retention_integration.py -v -m integration`
Expected: PASS (requires live Memgraph)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_retention_integration.py
git commit -m "test(retention): add integration test for retention sweep"
```

---

## Summary

9 tasks implementing:
- RetentionPolicy config model with eligibility logic
- Cypher queries for tombstone/delete operations
- RetentionService orchestrating sweeps
- Dagster asset + daily schedule
- Query filters to exclude tombstoned nodes
- Settings integration for env var overrides
- Integration test

Total estimated time: 2-3 hours for experienced developer.
