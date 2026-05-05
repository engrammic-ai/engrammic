# Hybrid Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split storage between Memgraph (graph-native) and Postgres (relational/audit/config) with ReasoningChain summary projection and Conclusion consolidation.

**Architecture:** Postgres-first saga for ReasoningChain writes (steps in Postgres, summary in Memgraph). Conclusion nodes aggregate multiple reasoning chains with async custodian consolidation. Redis locks prevent consolidation races.

**Tech Stack:** SQLAlchemy 2.0 async, Alembic migrations, redis-py locks, existing Memgraph/custodian infra.

**Spec:** `docs/superpowers/specs/2026-05-05-hybrid-storage-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|----------------|
| `src/context_service/models/postgres/__init__.py` | Package init, re-exports |
| `src/context_service/models/postgres/org.py` | OrgPreferences, SiloConfig models |
| `src/context_service/models/postgres/reasoning.py` | ReasoningChainSteps, OrphanedChains models |
| `src/context_service/models/postgres/audit.py` | Events, AuditEvents models |
| `src/context_service/engine/postgres_store.py` | Repository layer for Postgres operations |
| `src/context_service/engine/chain_saga.py` | ReasoningChain write saga with compensation |
| `src/context_service/custodian/consolidation.py` | Conclusion consolidation logic |
| `src/context_service/pipelines/assets/reconciliation.py` | Orphaned chain GC job |
| `alembic/versions/001_hybrid_storage.py` | Initial migration |
| `tests/test_postgres_models.py` | Model unit tests |
| `tests/test_chain_saga.py` | Saga write path tests |
| `tests/test_consolidation.py` | Consolidation logic tests |

### Modified Files
| File | Changes |
|------|---------|
| `src/context_service/models/inference.py` | Add Conclusion model |
| `src/context_service/db/queries.py` | Add Conclusion Cypher queries |
| `src/context_service/mcp/tools/context_store.py` | Use saga for intelligence layer |
| `src/context_service/mcp/tools/context_recall.py` | Add `include_steps` parameter |
| `src/context_service/custodian/dispatch.py` | Add consolidation pass |
| `src/context_service/api/app.py` | Init Postgres on startup |

---

## Phase 1: Postgres Models and Migration

### Task 1: Create Postgres Model Package

**Files:**
- Create: `src/context_service/models/postgres/__init__.py`
- Create: `src/context_service/models/postgres/org.py`
- Test: `tests/test_postgres_models.py`

- [ ] **Step 1: Write failing test for OrgPreferences model**

```python
# tests/test_postgres_models.py
import pytest
from sqlalchemy import inspect

from context_service.models.postgres.org import OrgPreferences, SiloConfig


def test_org_preferences_columns():
    """OrgPreferences has required columns."""
    mapper = inspect(OrgPreferences)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "org_id",
        "default_llm",
        "embedding_model",
        "settings",
        "created_at",
        "updated_at",
    }


def test_org_preferences_defaults():
    """OrgPreferences has correct defaults."""
    org = OrgPreferences(org_id="test-org")
    assert org.default_llm == "claude-haiku-4-5-20251001"
    assert org.embedding_model == "jina-embeddings-v3"
    assert org.settings == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_postgres_models.py -v`
Expected: FAIL with "No module named 'context_service.models.postgres'"

- [ ] **Step 3: Create package init**

```python
# src/context_service/models/postgres/__init__.py
"""Postgres SQLAlchemy models for hybrid storage."""

from context_service.models.postgres.org import OrgPreferences, SiloConfig

__all__ = ["OrgPreferences", "SiloConfig"]
```

- [ ] **Step 4: Implement OrgPreferences and SiloConfig models**

```python
# src/context_service/models/postgres/org.py
"""Organization and silo configuration models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from context_service.db.postgres import Base


class OrgPreferences(Base):
    """Organization-level preferences and settings."""

    __tablename__ = "org_preferences"

    org_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    default_llm: Mapped[str] = mapped_column(
        String(64), default="claude-haiku-4-5-20251001"
    )
    embedding_model: Mapped[str] = mapped_column(
        String(64), default="jina-embeddings-v3"
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    silos: Mapped[list["SiloConfig"]] = relationship(back_populates="org")


class SiloConfig(Base):
    """Per-silo configuration and quotas."""

    __tablename__ = "silo_config"

    silo_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("org_preferences.org_id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quotas: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    feature_flags: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    org: Mapped["OrgPreferences"] = relationship(back_populates="silos")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_postgres_models.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/models/postgres/ tests/test_postgres_models.py
git commit -m "feat(postgres): add OrgPreferences and SiloConfig models"
```

---

### Task 2: Add ReasoningChainSteps and OrphanedChains Models

**Files:**
- Create: `src/context_service/models/postgres/reasoning.py`
- Modify: `src/context_service/models/postgres/__init__.py`
- Test: `tests/test_postgres_models.py`

- [ ] **Step 1: Write failing test for ReasoningChainSteps**

```python
# tests/test_postgres_models.py (append)
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)


def test_reasoning_chain_steps_columns():
    """ReasoningChainSteps has required columns."""
    mapper = inspect(ReasoningChainSteps)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "chain_id",
        "silo_id",
        "steps",
        "created_at",
        "updated_at",
    }


def test_orphaned_chains_columns():
    """OrphanedChains has required columns for dead-letter."""
    mapper = inspect(OrphanedChains)
    columns = {c.key for c in mapper.columns}
    assert columns == {
        "chain_id",
        "silo_id",
        "failed_at",
        "retry_count",
        "last_error",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_postgres_models.py::test_reasoning_chain_steps_columns -v`
Expected: FAIL with "cannot import name 'ReasoningChainSteps'"

- [ ] **Step 3: Implement ReasoningChainSteps and OrphanedChains**

```python
# src/context_service/models/postgres/reasoning.py
"""ReasoningChain payload storage models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class ReasoningChainSteps(Base):
    """Full steps payload for ReasoningChain nodes (hot storage)."""

    __tablename__ = "reasoning_chain_steps"

    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("silo_config.silo_id"), nullable=False
    )
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("idx_chain_steps_silo", "silo_id"),)


class OrphanedChains(Base):
    """Dead-letter table for failed saga compensations."""

    __tablename__ = "orphaned_chains"

    chain_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    failed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    retry_count: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Update package init**

```python
# src/context_service/models/postgres/__init__.py
"""Postgres SQLAlchemy models for hybrid storage."""

from context_service.models.postgres.audit import AuditEvents, Events
from context_service.models.postgres.org import OrgPreferences, SiloConfig
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)

__all__ = [
    "AuditEvents",
    "Events",
    "OrgPreferences",
    "OrphanedChains",
    "ReasoningChainSteps",
    "SiloConfig",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_postgres_models.py -v`
Expected: FAIL (AuditEvents not yet created - expected, will fix in next task)

- [ ] **Step 6: Commit partial progress**

```bash
git add src/context_service/models/postgres/reasoning.py
git commit -m "feat(postgres): add ReasoningChainSteps and OrphanedChains models"
```

---

### Task 3: Add Events and AuditEvents Models

**Files:**
- Create: `src/context_service/models/postgres/audit.py`
- Modify: `src/context_service/models/postgres/__init__.py`
- Test: `tests/test_postgres_models.py`

- [ ] **Step 1: Write failing test for Events and AuditEvents**

```python
# tests/test_postgres_models.py (append)
from context_service.models.postgres.audit import AuditEvents, Events


def test_events_columns():
    """Events has required columns including expires_at for TTL."""
    mapper = inspect(Events)
    columns = {c.key for c in mapper.columns}
    assert "expires_at" in columns
    assert "silo_id" in columns
    assert "event_type" in columns


def test_audit_events_has_actor_fields():
    """AuditEvents tracks who triggered the event."""
    mapper = inspect(AuditEvents)
    columns = {c.key for c in mapper.columns}
    assert "actor_id" in columns
    assert "actor_type" in columns
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_postgres_models.py::test_events_columns -v`
Expected: FAIL with "cannot import name 'Events'"

- [ ] **Step 3: Implement Events and AuditEvents**

```python
# src/context_service/models/postgres/audit.py
"""Audit and event log models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from context_service.db.postgres import Base


class Events(Base):
    """Compacted reasoning trace events."""

    __tablename__ = "events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("silo_config.silo_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_chain_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    content: Mapped[str] = mapped_column(String, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    step_count: Mapped[int | None] = mapped_column(nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)

    __table_args__ = (
        Index("idx_events_silo_type", "silo_id", "event_type", "created_at"),
        Index(
            "idx_events_expiry", "expires_at", postgresql_where="expires_at IS NOT NULL"
        ),
    )


class AuditEvents(Base):
    """Audit trail for system events (erasure, calibration, etc.)."""

    __tablename__ = "audit_events"

    id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    silo_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("silo_config.silo_id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        Index("idx_audit_silo_time", "silo_id", "created_at"),
        Index("idx_audit_actor", "actor_id", "created_at"),
    )
```

- [ ] **Step 4: Run all model tests**

Run: `uv run pytest tests/test_postgres_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/models/postgres/
git commit -m "feat(postgres): add Events and AuditEvents models"
```

---

### Task 4: Create Alembic Migration

**Files:**
- Create: `alembic/versions/001_hybrid_storage.py`

- [ ] **Step 1: Check if alembic is configured**

Run: `ls alembic/ 2>/dev/null || echo "need to init alembic"`

If alembic not configured:
```bash
uv run alembic init alembic
```

- [ ] **Step 2: Generate migration from models**

```bash
uv run alembic revision --autogenerate -m "hybrid_storage_tables"
```

- [ ] **Step 3: Review and adjust generated migration**

The autogenerated migration should create:
- `org_preferences`
- `silo_config`
- `reasoning_chain_steps`
- `orphaned_chains`
- `events`
- `audit_events`

Verify FK constraints and indexes are correct.

- [ ] **Step 4: Test migration up/down**

```bash
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

- [ ] **Step 5: Commit**

```bash
git add alembic/
git commit -m "feat(postgres): add hybrid storage migration"
```

---

## Phase 2: ReasoningChain Saga Write Path

### Task 5: Add Conclusion Model to inference.py

**Files:**
- Modify: `src/context_service/models/inference.py`
- Test: `tests/test_postgres_models.py`

- [ ] **Step 1: Write failing test for Conclusion model**

```python
# tests/test_postgres_models.py (append)
from context_service.models.inference import Conclusion


def test_conclusion_model_fields():
    """Conclusion has required fields including valid_to."""
    conclusion = Conclusion(
        silo_id="test-silo",
        query_context_hash="abc123",
        content="User prefers X",
        confidence=0.9,
        created_by_agent_id="agent-1",
    )
    assert conclusion.status == "active"
    assert conclusion.valid_to is None
    assert hasattr(conclusion, "valid_from")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_postgres_models.py::test_conclusion_model_fields -v`
Expected: FAIL with "cannot import name 'Conclusion'"

- [ ] **Step 3: Add Conclusion model**

```python
# src/context_service/models/inference.py (append after ReasoningChain class)

class Conclusion(BaseModel):
    """A :Conclusion node - aggregates reasoning chains with consolidation.

    Node label: IntelligenceLabel.CONCLUSION
    """

    model_config = {"extra": "forbid"}

    node_label: str = "Conclusion"  # Add to IntelligenceLabel if not present

    silo_id: str
    query_context_hash: str
    content: str
    confidence: float = Field(ge=0.0, le=1.0)
    status: Literal["active", "consolidated"] = "active"
    created_by_agent_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_from: datetime = Field(default_factory=lambda: datetime.now(UTC))
    valid_to: datetime | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_postgres_models.py::test_conclusion_model_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/models/inference.py tests/test_postgres_models.py
git commit -m "feat(models): add Conclusion model for intelligence layer"
```

---

### Task 6: Create Postgres Repository Layer

**Files:**
- Create: `src/context_service/engine/postgres_store.py`
- Create: `tests/test_postgres_store.py`

- [ ] **Step 1: Write failing test for upsert_chain_steps**

```python
# tests/test_postgres_store.py
import pytest
from uuid import uuid4

from context_service.engine.postgres_store import PostgresStore


@pytest.fixture
def postgres_store():
    return PostgresStore()


@pytest.mark.asyncio
async def test_upsert_chain_steps(postgres_store):
    """upsert_chain_steps inserts and updates correctly."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [{"step_index": 0, "operation": "test", "conclusion": "done"}]

    # First insert
    await postgres_store.upsert_chain_steps(chain_id, silo_id, steps)
    result = await postgres_store.get_chain_steps(chain_id)
    assert result == steps

    # Update
    steps_v2 = [{"step_index": 0, "operation": "updated", "conclusion": "done"}]
    await postgres_store.upsert_chain_steps(chain_id, silo_id, steps_v2)
    result = await postgres_store.get_chain_steps(chain_id)
    assert result == steps_v2


@pytest.mark.asyncio
async def test_delete_chain_steps(postgres_store):
    """delete_chain_steps removes the row."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [{"step_index": 0, "operation": "test", "conclusion": "done"}]

    await postgres_store.upsert_chain_steps(chain_id, silo_id, steps)
    await postgres_store.delete_chain_steps(chain_id)
    result = await postgres_store.get_chain_steps(chain_id)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_postgres_store.py -v`
Expected: FAIL with "cannot import name 'PostgresStore'"

- [ ] **Step 3: Implement PostgresStore**

```python
# src/context_service/engine/postgres_store.py
"""Repository layer for Postgres hybrid storage operations."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from context_service.db.postgres import get_session
from context_service.models.postgres.reasoning import (
    OrphanedChains,
    ReasoningChainSteps,
)


class PostgresStore:
    """Async repository for Postgres-backed hybrid storage."""

    async def upsert_chain_steps(
        self, chain_id: UUID, silo_id: UUID, steps: list[dict[str, Any]]
    ) -> None:
        """Upsert reasoning chain steps with ON CONFLICT UPDATE."""
        async with get_session() as session:
            stmt = insert(ReasoningChainSteps).values(
                chain_id=chain_id,
                silo_id=silo_id,
                steps=steps,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["chain_id"],
                set_={"steps": stmt.excluded.steps, "updated_at": stmt.excluded.updated_at},
            )
            await session.execute(stmt)

    async def get_chain_steps(self, chain_id: UUID) -> list[dict[str, Any]] | None:
        """Fetch steps by chain_id. Returns None if not found."""
        async with get_session() as session:
            stmt = select(ReasoningChainSteps.steps).where(
                ReasoningChainSteps.chain_id == chain_id
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            return row

    async def delete_chain_steps(self, chain_id: UUID) -> bool:
        """Delete chain steps. Returns True if row existed."""
        async with get_session() as session:
            stmt = delete(ReasoningChainSteps).where(
                ReasoningChainSteps.chain_id == chain_id
            )
            result = await session.execute(stmt)
            return result.rowcount > 0

    async def add_orphaned_chain(
        self, chain_id: UUID, silo_id: UUID, error: str
    ) -> None:
        """Add chain to dead-letter table."""
        async with get_session() as session:
            stmt = insert(OrphanedChains).values(
                chain_id=chain_id,
                silo_id=silo_id,
                last_error=error,
                retry_count=1,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["chain_id"],
                set_={
                    "retry_count": OrphanedChains.retry_count + 1,
                    "last_error": error,
                },
            )
            await session.execute(stmt)
```

- [ ] **Step 4: Run test (requires test DB)**

Run: `uv run pytest tests/test_postgres_store.py -v -m "not integration"`

Note: These tests require a running Postgres. Mark as integration tests if needed.

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/postgres_store.py tests/test_postgres_store.py
git commit -m "feat(engine): add PostgresStore repository layer"
```

---

### Task 7: Implement Chain Saga Writer

**Files:**
- Create: `src/context_service/engine/chain_saga.py`
- Create: `tests/test_chain_saga.py`

- [ ] **Step 1: Write failing test for saga write**

```python
# tests/test_chain_saga.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from context_service.engine.chain_saga import ChainSagaWriter
from context_service.models.inference import ChainStep


@pytest.fixture
def mock_postgres_store():
    return AsyncMock()


@pytest.fixture
def mock_memgraph_store():
    return AsyncMock()


@pytest.fixture
def saga_writer(mock_postgres_store, mock_memgraph_store):
    return ChainSagaWriter(mock_postgres_store, mock_memgraph_store)


@pytest.mark.asyncio
async def test_saga_computes_summary_fields(saga_writer, mock_postgres_store, mock_memgraph_store):
    """Saga computes step_count, first_step, final_step from steps."""
    chain_id = uuid4()
    silo_id = uuid4()
    steps = [
        ChainStep(step_index=0, operation="retrieve", conclusion="Found data", confidence=0.9),
        ChainStep(step_index=1, operation="synthesize", conclusion="Final answer", confidence=0.95),
    ]

    await saga_writer.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model="claude",
        produced_by_agent_id="agent-1",
    )

    # Verify Postgres called first
    mock_postgres_store.upsert_chain_steps.assert_called_once()

    # Verify Memgraph called with summary fields
    call_args = mock_memgraph_store.upsert_reasoning_chain.call_args
    assert call_args.kwargs["step_count"] == 2
    assert "retrieve" in call_args.kwargs["first_step"]
    assert "synthesize" in call_args.kwargs["final_step"]


@pytest.mark.asyncio
async def test_saga_compensates_on_memgraph_failure(
    saga_writer, mock_postgres_store, mock_memgraph_store
):
    """On Memgraph failure, saga deletes Postgres row."""
    mock_memgraph_store.upsert_reasoning_chain.side_effect = Exception("Memgraph down")

    chain_id = uuid4()
    silo_id = uuid4()
    steps = [ChainStep(step_index=0, operation="test", conclusion="x", confidence=0.9)]

    with pytest.raises(Exception, match="Memgraph down"):
        await saga_writer.write_chain(
            chain_id=chain_id,
            silo_id=silo_id,
            steps=steps,
            produced_by_model="claude",
            produced_by_agent_id="agent-1",
        )

    # Verify compensation attempted
    mock_postgres_store.delete_chain_steps.assert_called_once_with(chain_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_chain_saga.py -v`
Expected: FAIL with "cannot import name 'ChainSagaWriter'"

- [ ] **Step 3: Implement ChainSagaWriter**

```python
# src/context_service/engine/chain_saga.py
"""Saga pattern for ReasoningChain writes across Postgres and Memgraph."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from context_service.engine.postgres_store import PostgresStore
    from context_service.stores.memgraph import HyperGraphStore
    from context_service.models.inference import ChainStep

log = structlog.get_logger()

_MAX_COMPENSATION_RETRIES = 3


class ChainSagaWriter:
    """Writes ReasoningChain with Postgres-first saga and compensation."""

    def __init__(self, postgres_store: "PostgresStore", memgraph_store: "HyperGraphStore"):
        self._pg = postgres_store
        self._mg = memgraph_store

    async def write_chain(
        self,
        chain_id: UUID,
        silo_id: UUID,
        steps: list["ChainStep"],
        produced_by_model: str,
        produced_by_agent_id: str,
        query_context_hash: str | None = None,
        status: str = "draft",
        source: str = "agent_explicit",
    ) -> None:
        """Write chain with saga pattern: Postgres first, Memgraph second.

        On Memgraph failure, compensates by deleting Postgres row.
        """
        # Compute summary fields
        step_count = len(steps)
        first_step = json.dumps(steps[0].model_dump()) if steps else None
        final_step = json.dumps(steps[-1].model_dump()) if steps else None
        all_premise_refs = []
        for step in steps:
            all_premise_refs.extend(step.premise_refs)
        outcome = self._derive_outcome(steps)

        # Step 1: Postgres write (can retry safely via ON CONFLICT)
        steps_data = [s.model_dump() for s in steps]
        await self._pg.upsert_chain_steps(chain_id, silo_id, steps_data)

        # Step 2: Memgraph write
        try:
            await self._mg.upsert_reasoning_chain(
                chain_id=str(chain_id),
                silo_id=str(silo_id),
                step_count=step_count,
                first_step=first_step,
                final_step=final_step,
                outcome=outcome,
                all_premise_refs=all_premise_refs,
                produced_by_model=produced_by_model,
                produced_by_agent_id=produced_by_agent_id,
                query_context_hash=query_context_hash,
                status=status,
                source=source,
            )
        except Exception as e:
            # Compensate: delete Postgres row
            await self._compensate(chain_id, silo_id, str(e))
            raise

    async def _compensate(self, chain_id: UUID, silo_id: UUID, error: str) -> None:
        """Attempt to delete Postgres row; dead-letter on failure."""
        for attempt in range(_MAX_COMPENSATION_RETRIES):
            try:
                await self._pg.delete_chain_steps(chain_id)
                log.info("saga_compensation_success", chain_id=str(chain_id))
                return
            except Exception as comp_err:
                log.warning(
                    "saga_compensation_retry",
                    chain_id=str(chain_id),
                    attempt=attempt + 1,
                    error=str(comp_err),
                )

        # All retries failed - dead-letter
        log.error("saga_compensation_failed", chain_id=str(chain_id), error=error)
        await self._pg.add_orphaned_chain(chain_id, silo_id, error)

    def _derive_outcome(self, steps: list["ChainStep"]) -> str | None:
        """Derive outcome from final step confidence."""
        if not steps:
            return None
        final_confidence = steps[-1].confidence
        if final_confidence >= 0.8:
            return "success"
        elif final_confidence >= 0.5:
            return "inconclusive"
        else:
            return "failure"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_chain_saga.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/engine/chain_saga.py tests/test_chain_saga.py
git commit -m "feat(engine): add ChainSagaWriter with compensation"
```

---

### Task 8: Add Conclusion Cypher Queries

**Files:**
- Modify: `src/context_service/db/queries.py`

- [ ] **Step 1: Add Conclusion queries to queries.py**

```python
# src/context_service/db/queries.py (append)

# --- Conclusion queries ---

UPSERT_CONCLUSION = """
MERGE (c:Conclusion {id: $id})
ON CREATE SET
    c.silo_id = $silo_id,
    c.query_context_hash = $query_context_hash,
    c.content = $content,
    c.confidence = $confidence,
    c.status = $status,
    c.created_by_agent_id = $created_by_agent_id,
    c.created_at = $created_at,
    c.valid_from = $valid_from,
    c.valid_to = null
ON MATCH SET
    c.content = $content,
    c.confidence = $confidence,
    c.status = $status
RETURN c
"""

CREATE_CONCLUDES_EDGE = """
MATCH (chain:ReasoningChain {id: $chain_id})
MATCH (conclusion:Conclusion {id: $conclusion_id})
MERGE (chain)-[:CONCLUDES]->(conclusion)
"""

CREATE_CONSOLIDATES_EDGE = """
MATCH (canonical:Conclusion {id: $canonical_id})
MATCH (original:Conclusion {id: $original_id})
MERGE (canonical)-[:CONSOLIDATES]->(original)
"""

GET_CONCLUSIONS_BY_HASH = """
MATCH (c:Conclusion {silo_id: $silo_id, query_context_hash: $query_context_hash})
WHERE c.status = 'active'
RETURN c
"""

MARK_CONCLUSION_CONSOLIDATED = """
MATCH (c:Conclusion {id: $id})
SET c.status = 'consolidated'
RETURN c
"""

FIND_ORPHANED_ACTIVE_CONCLUSIONS = """
MATCH (canonical:Conclusion)-[:CONSOLIDATES]->(original:Conclusion)
WHERE original.status = 'active'
RETURN original.id as id
"""
```

- [ ] **Step 2: Verify syntax with typecheck**

Run: `uv run mypy src/context_service/db/queries.py`
Expected: PASS (queries are just strings)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add Conclusion Cypher queries"
```

---

## Phase 3: API Changes

### Task 9: Update context_recall with include_steps

**Files:**
- Modify: `src/context_service/mcp/tools/context_recall.py`
- Create: `tests/test_context_recall_steps.py`

- [ ] **Step 1: Write failing test for include_steps**

```python
# tests/test_context_recall_steps.py
import pytest
from unittest.mock import AsyncMock, patch
from uuid import uuid4


@pytest.mark.asyncio
async def test_context_recall_includes_steps_when_requested():
    """include_steps=True fetches steps from Postgres."""
    from context_service.mcp.tools.context_recall import _context_recall

    chain_id = str(uuid4())
    silo_id = str(uuid4())

    mock_steps = [{"step_index": 0, "operation": "test", "conclusion": "done"}]

    with patch("context_service.mcp.tools.context_recall._context_get") as mock_get:
        mock_get.return_value = {
            "nodes": [
                {
                    "node_id": chain_id,
                    "layer": "intelligence",
                    "step_count": 1,
                    "first_step": '{"operation": "test"}',
                    "final_step": '{"operation": "test"}',
                }
            ]
        }

        with patch("context_service.mcp.tools.context_recall._fetch_chain_steps") as mock_fetch:
            mock_fetch.return_value = {chain_id: mock_steps}

            result = await _context_recall(
                silo_id=silo_id,
                node_ids=[chain_id],
                include_steps=True,
            )

            assert result["nodes"][0]["steps"] == mock_steps
            mock_fetch.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_context_recall_steps.py -v`
Expected: FAIL (include_steps parameter not yet added)

- [ ] **Step 3: Add include_steps parameter and fetch logic**

```python
# src/context_service/mcp/tools/context_recall.py

# Add import at top
from context_service.engine.postgres_store import PostgresStore

# Add helper function
async def _fetch_chain_steps(chain_ids: list[str]) -> dict[str, list[dict]]:
    """Fetch steps from Postgres for given chain IDs."""
    store = PostgresStore()
    result = {}
    for chain_id in chain_ids:
        steps = await store.get_chain_steps(chain_id)
        if steps:
            result[chain_id] = steps
    return result


# Modify _context_recall signature and implementation
async def _context_recall(
    silo_id: str,
    query: str | None = None,
    node_ids: list[str] | None = None,
    depth: int = 0,
    layers: list[str] | None = None,
    top_k: int = 10,
    as_of: str | None = None,
    include_reflections: bool = False,
    reflections_agent_id: str | None = None,
    include_steps: bool = False,  # NEW
) -> dict[str, Any]:
    """Internal implementation for testing."""
    if not query and not node_ids:
        return {"error": "missing_input", "message": "Provide query or node_ids"}

    if node_ids and depth == 0:
        result = await _context_get(
            node_ids=node_ids,
            silo_id=silo_id,
            as_of=as_of,
            include_reflections=include_reflections,
            reflections_agent_id=reflections_agent_id,
        )

        # Fetch steps if requested and we have intelligence layer nodes
        if include_steps and "nodes" in result:
            chain_ids = [
                n["node_id"]
                for n in result["nodes"]
                if n.get("layer") == "intelligence"
            ]
            if chain_ids:
                steps_map = await _fetch_chain_steps(chain_ids)
                for node in result["nodes"]:
                    if node["node_id"] in steps_map:
                        node["steps"] = steps_map[node["node_id"]]

        return result

    # ... rest of function unchanged
```

- [ ] **Step 4: Update MCP tool signature**

In the `@mcp.tool()` decorated function, add `include_steps: bool = False` parameter and pass to `_context_recall`.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_context_recall_steps.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/context_service/mcp/tools/context_recall.py tests/test_context_recall_steps.py
git commit -m "feat(mcp): add include_steps parameter to context_recall"
```

---

### Task 10: Update context_store to Use Saga

**Files:**
- Modify: `src/context_service/mcp/tools/context_store.py`

- [ ] **Step 1: Identify intelligence layer write path**

Find the section handling `layer="intelligence"` writes.

- [ ] **Step 2: Replace direct Memgraph write with saga**

```python
# In context_store.py, modify the intelligence layer handler

from context_service.engine.chain_saga import ChainSagaWriter
from context_service.engine.postgres_store import PostgresStore

# In the intelligence layer write path:
if layer == "intelligence":
    postgres_store = PostgresStore()
    memgraph_store = get_memgraph_store()  # existing helper
    saga = ChainSagaWriter(postgres_store, memgraph_store)

    await saga.write_chain(
        chain_id=chain_id,
        silo_id=silo_id,
        steps=steps,
        produced_by_model=produced_by_model,
        produced_by_agent_id=agent_id,
        query_context_hash=query_context_hash,
        status=status,
        source=source,
    )
```

- [ ] **Step 3: Run existing tests**

Run: `uv run pytest tests/ -k "context_store" -v`
Expected: PASS (existing tests should still work)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/mcp/tools/context_store.py
git commit -m "feat(mcp): use ChainSagaWriter for intelligence layer writes"
```

---

## Phase 4: Custodian Consolidation

### Task 11: Implement Consolidation Logic

**Files:**
- Create: `src/context_service/custodian/consolidation.py`
- Create: `tests/test_consolidation.py`

- [ ] **Step 1: Write failing test for consolidation**

```python
# tests/test_consolidation.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from context_service.custodian.consolidation import ConclusionConsolidator


@pytest.fixture
def mock_memgraph():
    return AsyncMock()


@pytest.fixture
def mock_redis():
    lock = MagicMock()
    lock.__aenter__ = AsyncMock(return_value=None)
    lock.__aexit__ = AsyncMock(return_value=None)
    redis = MagicMock()
    redis.lock.return_value = lock
    return redis


@pytest.fixture
def consolidator(mock_memgraph, mock_redis):
    return ConclusionConsolidator(mock_memgraph, mock_redis)


@pytest.mark.asyncio
async def test_consolidate_skips_single_conclusion(consolidator, mock_memgraph):
    """No consolidation when only one conclusion exists."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.9}
    ]

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is None  # No consolidation needed


@pytest.mark.asyncio
async def test_consolidate_creates_canonical(consolidator, mock_memgraph, mock_redis):
    """Creates canonical when 2+ conclusions share hash."""
    mock_memgraph.get_conclusions_by_hash.return_value = [
        {"id": "c1", "status": "active", "confidence": 0.8, "content": "Answer A"},
        {"id": "c2", "status": "active", "confidence": 0.9, "content": "Answer A"},
    ]

    result = await consolidator.consolidate_by_hash("silo-1", "hash-1")

    assert result is not None
    mock_memgraph.upsert_conclusion.assert_called_once()
    # Verify confidence boost
    call_kwargs = mock_memgraph.upsert_conclusion.call_args.kwargs
    assert call_kwargs["confidence"] > 0.9  # Agreement boost
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_consolidation.py -v`
Expected: FAIL with "cannot import name 'ConclusionConsolidator'"

- [ ] **Step 3: Implement ConclusionConsolidator**

```python
# src/context_service/custodian/consolidation.py
"""Conclusion consolidation for multi-writer reasoning chains."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import uuid4

import structlog

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from context_service.stores.memgraph import HyperGraphStore

log = structlog.get_logger()

_LOCK_TTL_SECONDS = 10
_EMBEDDING_SIMILARITY_THRESHOLD = 0.85


class ConclusionConsolidator:
    """Consolidates multiple Conclusions into canonical form."""

    def __init__(self, memgraph: "HyperGraphStore", redis: "Redis"):
        self._mg = memgraph
        self._redis = redis

    async def consolidate_by_hash(
        self, silo_id: str, query_context_hash: str
    ) -> str | None:
        """Consolidate conclusions with matching (silo_id, hash).

        Returns canonical conclusion ID if consolidation occurred, None otherwise.
        """
        lock_key = f"consolidation:{silo_id}:{query_context_hash}"

        async with self._redis.lock(lock_key, timeout=_LOCK_TTL_SECONDS):
            conclusions = await self._mg.get_conclusions_by_hash(
                silo_id, query_context_hash
            )

            # Filter to active only
            active = [c for c in conclusions if c.get("status") == "active"]

            if len(active) < 2:
                return None  # Nothing to consolidate

            # Idempotency: skip if any already consolidated
            if any(c.get("status") == "consolidated" for c in conclusions):
                log.info("consolidation_skipped_idempotent", hash=query_context_hash)
                return None

            return await self._create_canonical(silo_id, query_context_hash, active)

    async def _create_canonical(
        self, silo_id: str, query_context_hash: str, originals: list[dict[str, Any]]
    ) -> str:
        """Create canonical conclusion from originals."""
        canonical_id = str(uuid4())

        # Merge confidence with agreement boost
        avg_confidence = sum(c["confidence"] for c in originals) / len(originals)
        agreement_boost = min(0.1, 0.02 * len(originals))
        merged_confidence = min(1.0, avg_confidence + agreement_boost)

        # Use highest-confidence original's content
        best = max(originals, key=lambda c: c["confidence"])

        await self._mg.upsert_conclusion(
            id=canonical_id,
            silo_id=silo_id,
            query_context_hash=query_context_hash,
            content=best["content"],
            confidence=merged_confidence,
            status="active",
            created_by_agent_id="custodian:consolidation",
        )

        # Create CONSOLIDATES edges and mark originals
        for orig in originals:
            await self._mg.create_consolidates_edge(canonical_id, orig["id"])
            await self._mg.mark_conclusion_consolidated(orig["id"])

        log.info(
            "consolidation_complete",
            canonical_id=canonical_id,
            original_count=len(originals),
        )

        return canonical_id

    async def repair_orphaned_consolidations(self, silo_id: str) -> int:
        """Find and repair active conclusions with CONSOLIDATES edges.

        Returns count of repaired conclusions.
        """
        orphaned_ids = await self._mg.find_orphaned_active_conclusions(silo_id)

        for conclusion_id in orphaned_ids:
            await self._mg.mark_conclusion_consolidated(conclusion_id)

        return len(orphaned_ids)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_consolidation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/consolidation.py tests/test_consolidation.py
git commit -m "feat(custodian): add ConclusionConsolidator with locking"
```

---

### Task 12: Add Consolidation Pass to Custodian Dispatch

**Files:**
- Modify: `src/context_service/custodian/dispatch.py`

- [ ] **Step 1: Read current dispatch.py structure**

```bash
cat src/context_service/custodian/dispatch.py
```

- [ ] **Step 2: Add consolidation pass after validation**

```python
# Add to dispatch.py

from context_service.custodian.consolidation import ConclusionConsolidator

async def run_consolidation_pass(silo_id: str) -> dict[str, int]:
    """Run conclusion consolidation for a silo."""
    consolidator = ConclusionConsolidator(
        memgraph=get_memgraph_store(),
        redis=get_redis_client(),
    )

    # Get all active query_context_hashes with 2+ conclusions
    hashes = await get_memgraph_store().get_consolidation_candidates(silo_id)

    consolidated = 0
    for hash_val in hashes:
        result = await consolidator.consolidate_by_hash(silo_id, hash_val)
        if result:
            consolidated += 1

    # Repair any orphaned from previous crashes
    repaired = await consolidator.repair_orphaned_consolidations(silo_id)

    return {"consolidated": consolidated, "repaired": repaired}
```

- [ ] **Step 3: Wire into custodian worker loop**

Add `run_consolidation_pass` call after the validation pass in the main worker loop.

- [ ] **Step 4: Run existing custodian tests**

Run: `uv run pytest tests/ -k "custodian" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/dispatch.py
git commit -m "feat(custodian): add consolidation pass to worker loop"
```

---

## Phase 5: Reconciliation GC Job

### Task 13: Create Orphaned Chain Reconciliation Job

**Files:**
- Create: `src/context_service/pipelines/assets/reconciliation.py`
- Modify: `src/context_service/pipelines/definitions.py`

- [ ] **Step 1: Create reconciliation asset**

```python
# src/context_service/pipelines/assets/reconciliation.py
"""Dagster asset for orphaned chain reconciliation."""

from datetime import UTC, datetime, timedelta

import structlog
from dagster import asset, AssetExecutionContext

from context_service.engine.postgres_store import PostgresStore
from context_service.stores.memgraph import get_memgraph_store

log = structlog.get_logger()

_GRACE_PERIOD_MINUTES = 5


@asset(
    group_name="maintenance",
    description="Reconcile orphaned Postgres chain steps with no Memgraph node",
)
async def reconcile_orphaned_chains(context: AssetExecutionContext) -> dict:
    """Delete Postgres rows older than grace period with no Memgraph node."""
    pg = PostgresStore()
    mg = get_memgraph_store()

    cutoff = datetime.now(UTC) - timedelta(minutes=_GRACE_PERIOD_MINUTES)

    # Get all chain_ids from Postgres older than cutoff
    pg_chain_ids = await pg.get_chain_ids_before(cutoff)

    deleted = 0
    for chain_id in pg_chain_ids:
        # Check if Memgraph node exists
        exists = await mg.node_exists("ReasoningChain", str(chain_id))
        if not exists:
            await pg.delete_chain_steps(chain_id)
            deleted += 1
            log.info("reconciled_orphan", chain_id=str(chain_id))

    # Also process dead-letter table
    dead_letter_processed = await pg.process_dead_letter_queue()

    context.log.info(f"Reconciled {deleted} orphans, processed {dead_letter_processed} dead-letters")

    return {
        "orphans_deleted": deleted,
        "dead_letters_processed": dead_letter_processed,
    }
```

- [ ] **Step 2: Add helper methods to PostgresStore**

```python
# Add to src/context_service/engine/postgres_store.py

async def get_chain_ids_before(self, cutoff: datetime) -> list[UUID]:
    """Get chain_ids created before cutoff time."""
    async with get_session() as session:
        stmt = select(ReasoningChainSteps.chain_id).where(
            ReasoningChainSteps.created_at < cutoff
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]

async def process_dead_letter_queue(self) -> int:
    """Process and clean up dead-letter entries."""
    async with get_session() as session:
        # Delete entries older than 24 hours
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        stmt = delete(OrphanedChains).where(OrphanedChains.failed_at < cutoff)
        result = await session.execute(stmt)
        return result.rowcount
```

- [ ] **Step 3: Add to Dagster definitions**

```python
# In src/context_service/pipelines/definitions.py

from context_service.pipelines.assets.reconciliation import reconcile_orphaned_chains

# Add to assets list
defs = Definitions(
    assets=[
        # ... existing assets
        reconcile_orphaned_chains,
    ],
    schedules=[
        # Add schedule for reconciliation
        ScheduleDefinition(
            job=define_asset_job("reconciliation_job", selection=[reconcile_orphaned_chains]),
            cron_schedule="*/15 * * * *",  # Every 15 minutes
        ),
    ],
)
```

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/assets/reconciliation.py
git add src/context_service/pipelines/definitions.py
git add src/context_service/engine/postgres_store.py
git commit -m "feat(pipelines): add orphaned chain reconciliation job"
```

---

## Phase 6: App Initialization

### Task 14: Initialize Postgres on App Startup

**Files:**
- Modify: `src/context_service/api/app.py`

- [ ] **Step 1: Add Postgres init to lifespan**

```python
# In src/context_service/api/app.py

from context_service.db.postgres import init_postgres, close_postgres

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_postgres()
    # ... existing startup code

    yield

    # Shutdown
    await close_postgres()
    # ... existing shutdown code
```

- [ ] **Step 2: Run app startup test**

Run: `uv run python -c "from context_service.api.app import create_app; app = create_app()"`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/context_service/api/app.py
git commit -m "feat(api): initialize Postgres on app startup"
```

---

## Final Verification

### Task 15: Integration Test

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

- [ ] **Step 2: Run typecheck**

```bash
uv run mypy src/context_service/
```

- [ ] **Step 3: Run linter**

```bash
uv run ruff check src/ tests/
```

- [ ] **Step 4: Manual smoke test**

```bash
# Start services
just docker-up

# Run migration
uv run alembic upgrade head

# Start dev server
just dev

# Test via MCP (in another terminal)
# ... exercise context_store and context_recall with intelligence layer
```

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: complete hybrid storage implementation"
```

---

## Summary

| Phase | Tasks | Key Files |
|-------|-------|-----------|
| 1. Postgres Models | 1-4 | `models/postgres/*.py`, migration |
| 2. Saga Write | 5-8 | `chain_saga.py`, `postgres_store.py` |
| 3. API Changes | 9-10 | `context_recall.py`, `context_store.py` |
| 4. Consolidation | 11-12 | `consolidation.py`, `dispatch.py` |
| 5. GC Job | 13 | `reconciliation.py` |
| 6. Init | 14-15 | `app.py`, integration tests |
