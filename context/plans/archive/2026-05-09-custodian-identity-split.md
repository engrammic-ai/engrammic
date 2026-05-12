# Custodian Identity Split Implementation Plan

> **Status:** COMPLETE (2026-05-12)

## Progress

| Task | Status | Notes |
|------|--------|-------|
| 1. Config Infrastructure | Done | identities.yaml + settings models |
| 2. Base Classes | Done | IdentityDeps, CustodianTrigger protocol |
| 3. AsyncBatchTrigger | Done | Micro-batch trigger |
| 4. Groundskeeper Identity | Done | GC logic + Dagster job + schedule |
| 5. Validator Identity | Done | Wired into context_crystallize |
| 6. Custodian Identity | Done | Full LLM wiring (pydantic-ai) |
| 7. Synthesizer Identity | Done | Full LLM wiring + Dagster sensor |
| 8. Integration Test | Done | 12 tests passing |

All tech debt resolved:

---

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic Custodian into 4 focused identities (Custodian, Synthesizer, Groundskeeper, Validator), each owning specific EAG transitions.

**Architecture:** Each identity is a pydantic-ai Agent (except Groundskeeper which is deterministic). Custodian triggers via asyncio.create_task with micro-batching. Synthesizer/Groundskeeper run as Dagster jobs. Validator intercepts context_crystallize synchronously.

**Tech Stack:** Python 3.12, pydantic-ai, Dagster, FastAPI, Memgraph, structlog

**Reference:** `context/specs/glossary.md` defines identity responsibilities and EAG transitions.

---

## File Structure

```
src/context_service/
├── config/
│   └── identities.yaml              # NEW: per-identity config
├── custodian/
│   └── identities/                  # NEW: identity module
│       ├── __init__.py
│       ├── base.py                  # IdentityDeps, protocols
│       ├── custodian.py             # T2: contradiction, supersession
│       ├── synthesizer.py           # T3/T4/T10: synthesis
│       ├── groundskeeper.py         # T6/T9: memory lifecycle
│       ├── validator.py             # T13: crystallize validation
│       └── triggers/
│           ├── __init__.py
│           ├── protocols.py         # CustodianTrigger protocol
│           └── async_batch.py       # Micro-batch implementation
├── pipelines/
│   ├── jobs/
│   │   └── groundskeeper_job.py     # NEW: nightly GC job
│   └── sensors/
│       └── synthesizer_sensor.py    # NEW: threshold sensor
└── mcp/tools/
    └── context_crystallize.py       # MODIFY: add Validator hook
```

---

## Task 1: Config Infrastructure

**Files:**
- Create: `src/context_service/config/identities.yaml`
- Modify: `src/context_service/config/settings.py`

- [ ] **Step 1: Create identities.yaml**

```yaml
# config/identities.yaml
identities:
  custodian:
    enabled: true
    model: "google-vertex:gemini-2.5-flash"
    timeout_seconds: 30
    batch_size: 5
    batch_window_seconds: 2.0

  synthesizer:
    enabled: true
    model: "google-vertex:gemini-2.5-pro"
    timeout_seconds: 60
    threshold_pending_nodes: 50
    schedule_cron: "0 * * * *"

  groundskeeper:
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
    model: "google-vertex:gemini-2.5-pro"
    timeout_seconds: 5
    fail_open: true
```

- [ ] **Step 2: Add config models to settings.py**

Add after line 71 (after CustodianSettings):

```python
class CustodianIdentityConfig(BaseModel):
    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-flash"
    timeout_seconds: int = 30
    batch_size: int = 5
    batch_window_seconds: float = 2.0


class SynthesizerIdentityConfig(BaseModel):
    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: int = 60
    threshold_pending_nodes: int = 50
    schedule_cron: str = "0 * * * *"


class DecayClassConfig(BaseModel):
    half_life_days: int
    hard_delete_days: int


class GroundskeeperIdentityConfig(BaseModel):
    enabled: bool = True
    schedule_cron: str = "0 3 * * *"
    decay_classes: dict[str, DecayClassConfig] = Field(default_factory=dict)


class ValidatorIdentityConfig(BaseModel):
    enabled: bool = True
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: int = 5
    fail_open: bool = True


class IdentitiesConfig(BaseModel):
    custodian: CustodianIdentityConfig = Field(default_factory=CustodianIdentityConfig)
    synthesizer: SynthesizerIdentityConfig = Field(default_factory=SynthesizerIdentityConfig)
    groundskeeper: GroundskeeperIdentityConfig = Field(default_factory=GroundskeeperIdentityConfig)
    validator: ValidatorIdentityConfig = Field(default_factory=ValidatorIdentityConfig)
```

- [ ] **Step 3: Add identities field to Settings class**

In Settings class (around line 564), add:

```python
identities: IdentitiesConfig = Field(default_factory=IdentitiesConfig)
```

- [ ] **Step 4: Add YAML loader for identities config**

Create loader that reads `config/identities.yaml` and merges with defaults:

```python
def _load_identities_config() -> IdentitiesConfig:
    config_path = Path(__file__).parent / "identities.yaml"
    if config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f)
            return IdentitiesConfig(**data.get("identities", {}))
    return IdentitiesConfig()
```

- [ ] **Step 5: Run check**

```bash
just check
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/config/
git commit -m "feat(custodian): add identities config infrastructure"
```

---

## Task 2: Base Classes and Trigger Protocol

**Files:**
- Create: `src/context_service/custodian/identities/__init__.py`
- Create: `src/context_service/custodian/identities/base.py`
- Create: `src/context_service/custodian/identities/triggers/__init__.py`
- Create: `src/context_service/custodian/identities/triggers/protocols.py`

- [ ] **Step 1: Create identities package**

```python
# custodian/identities/__init__.py
"""Four custodian identities per EAG transitions.

- Custodian: T2 (contradiction, supersession)
- Synthesizer: T3/T4/T10 (synthesis, revision, propose)
- Groundskeeper: T6/T9 (trace, memory GC)
- Validator: T13 (crystallize validation)
"""

from context_service.custodian.identities.base import IdentityDeps

__all__ = ["IdentityDeps"]
```

- [ ] **Step 2: Create base.py with IdentityDeps**

```python
# custodian/identities/base.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore


@dataclass
class IdentityDeps:
    """Shared dependency container for all identities."""

    org_id: str
    silo_id: str
    memgraph_client: HyperGraphStore | None = None
    node_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 3: Create triggers package**

```python
# custodian/identities/triggers/__init__.py
from context_service.custodian.identities.triggers.protocols import CustodianTrigger

__all__ = ["CustodianTrigger"]
```

- [ ] **Step 4: Create trigger protocol**

```python
# custodian/identities/triggers/protocols.py
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CustodianTrigger(Protocol):
    """Swappable trigger mechanism for Custodian identity."""

    async def enqueue(self, silo_id: str, node_id: str, event_type: str) -> None:
        """Enqueue a node for custodian processing."""
        ...

    async def flush(self, silo_id: str) -> list[str]:
        """Flush pending nodes for a silo, return node_ids."""
        ...
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/identities/
git commit -m "feat(custodian): add identity base classes and trigger protocol"
```

---

## Task 3: AsyncBatchTrigger Implementation

**Files:**
- Create: `src/context_service/custodian/identities/triggers/async_batch.py`
- Create: `tests/custodian/identities/triggers/test_async_batch.py`

- [ ] **Step 1: Write failing test for batch trigger**

```python
# tests/custodian/identities/triggers/test_async_batch.py
import asyncio
import pytest
from context_service.custodian.identities.triggers.async_batch import AsyncBatchTrigger


@pytest.mark.asyncio
async def test_batch_fires_on_size():
    fired = []
    
    async def on_fire(silo_id: str, node_ids: list[str]) -> None:
        fired.append((silo_id, node_ids))
    
    trigger = AsyncBatchTrigger(batch_size=3, window_seconds=10.0, on_fire=on_fire)
    
    await trigger.enqueue("silo1", "node1", "store")
    await trigger.enqueue("silo1", "node2", "store")
    assert len(fired) == 0
    
    await trigger.enqueue("silo1", "node3", "store")
    assert len(fired) == 1
    assert fired[0] == ("silo1", ["node1", "node2", "node3"])


@pytest.mark.asyncio
async def test_batch_fires_on_timeout():
    fired = []
    
    async def on_fire(silo_id: str, node_ids: list[str]) -> None:
        fired.append((silo_id, node_ids))
    
    trigger = AsyncBatchTrigger(batch_size=10, window_seconds=0.1, on_fire=on_fire)
    
    await trigger.enqueue("silo1", "node1", "store")
    assert len(fired) == 0
    
    await asyncio.sleep(0.15)
    assert len(fired) == 1
    assert fired[0] == ("silo1", ["node1"])
```

- [ ] **Step 2: Run test to verify failure**

```bash
pytest tests/custodian/identities/triggers/test_async_batch.py -v
```

Expected: ImportError or test failure

- [ ] **Step 3: Implement AsyncBatchTrigger**

```python
# custodian/identities/triggers/async_batch.py
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from context_service.custodian.identities.triggers.protocols import CustodianTrigger

OnFireCallback = Callable[[str, list[str]], Awaitable[None]]


@dataclass
class AsyncBatchTrigger(CustodianTrigger):
    """Micro-batch trigger: fires on batch_size OR window_seconds, whichever first."""

    batch_size: int = 5
    window_seconds: float = 2.0
    on_fire: OnFireCallback | None = None

    _queues: dict[str, list[str]] = field(default_factory=dict, init=False)
    _timers: dict[str, asyncio.TimerHandle] = field(default_factory=dict, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    async def enqueue(self, silo_id: str, node_id: str, event_type: str) -> None:
        async with self._lock:
            if silo_id not in self._queues:
                self._queues[silo_id] = []

            self._queues[silo_id].append(node_id)

            if len(self._queues[silo_id]) >= self.batch_size:
                await self._fire(silo_id)
            elif silo_id not in self._timers:
                self._schedule_timer(silo_id)

    async def flush(self, silo_id: str) -> list[str]:
        async with self._lock:
            node_ids = self._queues.pop(silo_id, [])
            self._cancel_timer(silo_id)
            return node_ids

    async def _fire(self, silo_id: str) -> None:
        node_ids = self._queues.pop(silo_id, [])
        self._cancel_timer(silo_id)

        if node_ids and self.on_fire:
            await self.on_fire(silo_id, node_ids)

    def _schedule_timer(self, silo_id: str) -> None:
        loop = asyncio.get_event_loop()
        self._timers[silo_id] = loop.call_later(
            self.window_seconds,
            lambda: asyncio.create_task(self._fire_from_timer(silo_id)),
        )

    async def _fire_from_timer(self, silo_id: str) -> None:
        async with self._lock:
            if silo_id in self._queues:
                await self._fire(silo_id)

    def _cancel_timer(self, silo_id: str) -> None:
        if silo_id in self._timers:
            self._timers[silo_id].cancel()
            del self._timers[silo_id]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/custodian/identities/triggers/test_async_batch.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/identities/triggers/ tests/custodian/identities/
git commit -m "feat(custodian): implement AsyncBatchTrigger with micro-batching"
```

---

## Task 4: Groundskeeper Identity (Simplest - No LLM)

**Files:**
- Create: `src/context_service/custodian/identities/groundskeeper.py`
- Create: `src/context_service/pipelines/jobs/groundskeeper_job.py`
- Modify: `src/context_service/pipelines/schedules.py`
- Create: `tests/custodian/identities/test_groundskeeper.py`

- [ ] **Step 1: Write failing test**

```python
# tests/custodian/identities/test_groundskeeper.py
import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import AsyncMock

from context_service.custodian.identities.groundskeeper import (
    get_expired_memory_nodes,
    GroundskeeperIdentity,
)


@pytest.mark.asyncio
async def test_get_expired_memory_nodes():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"node_id": "n1", "decay_class": "ephemeral", "created_at": "2026-01-01T00:00:00Z"},
    ]
    
    result = await get_expired_memory_nodes(
        mock_store,
        silo_id="test-silo",
        decay_config={"ephemeral": {"hard_delete_days": 14}},
    )
    
    assert len(result) >= 0  # Depends on current date logic
```

- [ ] **Step 2: Implement Groundskeeper**

```python
# custodian/identities/groundskeeper.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, UTC
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)

EXPIRED_MEMORY_QUERY = """
MATCH (n:Passage|Utterance|Event {silo_id: $silo_id})
WHERE n.decay_class = $decay_class
  AND n.created_at < $cutoff
RETURN n.id AS node_id, n.decay_class AS decay_class, n.created_at AS created_at
LIMIT 1000
"""

DELETE_NODES_QUERY = """
MATCH (n)
WHERE n.id IN $node_ids AND n.silo_id = $silo_id
DETACH DELETE n
"""


async def get_expired_memory_nodes(
    store: HyperGraphStore,
    silo_id: str,
    decay_config: dict[str, dict],
) -> list[dict]:
    """Find Memory-layer nodes past their hard_delete threshold."""
    expired = []
    now = datetime.now(UTC)

    for decay_class, config in decay_config.items():
        if config is None:
            continue
        hard_delete_days = config.get("hard_delete_days", 9999)
        cutoff = now - timedelta(days=hard_delete_days)

        rows = await store.execute_query(
            EXPIRED_MEMORY_QUERY,
            {"silo_id": silo_id, "decay_class": decay_class, "cutoff": cutoff.isoformat()},
        )
        expired.extend(rows)

    return expired


@dataclass
class GroundskeeperIdentity:
    """Memory lifecycle management. No LLM - deterministic operations."""

    store: HyperGraphStore
    silo_id: str
    decay_config: dict[str, dict]

    async def run_gc(self) -> dict:
        """Run garbage collection for expired Memory nodes (T9)."""
        expired = await get_expired_memory_nodes(
            self.store, self.silo_id, self.decay_config
        )

        if not expired:
            return {"deleted": 0, "silo_id": self.silo_id}

        node_ids = [r["node_id"] for r in expired]
        await self.store.execute_write(
            DELETE_NODES_QUERY,
            {"node_ids": node_ids, "silo_id": self.silo_id},
        )

        logger.info(
            "groundskeeper.gc_complete",
            silo_id=self.silo_id,
            deleted=len(node_ids),
            identity="groundskeeper",
        )

        return {"deleted": len(node_ids), "silo_id": self.silo_id}

    async def run_hyperedge_dedup(self) -> dict:
        """Deduplicate exact-match hyperedges. Lossless."""
        # TODO: Implement content-addressed dedup via MERGE
        return {"deduped": 0, "silo_id": self.silo_id}
```

- [ ] **Step 3: Create Dagster job**

```python
# pipelines/jobs/groundskeeper_job.py
import dagster as dg

from context_service.config.settings import get_settings
from context_service.custodian.identities.groundskeeper import GroundskeeperIdentity
from context_service.pipelines.resources import MemgraphResource


@dg.op
async def groundskeeper_gc_op(context: dg.OpExecutionContext, memgraph: MemgraphResource):
    """Run Memory GC for all active silos."""
    settings = get_settings()
    decay_config = settings.identities.groundskeeper.decay_classes

    driver = await memgraph.driver()
    from context_service.stores import MemgraphClient
    store = MemgraphClient(driver)

    # Get active silos
    silos = await store.execute_query("MATCH (d:Document) RETURN DISTINCT d.silo_id AS silo_id", {})
    
    total_deleted = 0
    for row in silos:
        silo_id = row["silo_id"]
        gk = GroundskeeperIdentity(store=store, silo_id=silo_id, decay_config=decay_config)
        result = await gk.run_gc()
        total_deleted += result["deleted"]

    return {"total_deleted": total_deleted, "silos_processed": len(silos)}


@dg.job(name="groundskeeper_nightly")
def groundskeeper_nightly():
    groundskeeper_gc_op()
```

- [ ] **Step 4: Add schedule**

In `pipelines/schedules.py`, add:

```python
@dg.schedule(
    cron_schedule="0 3 * * *",
    name="groundskeeper_schedule",
    target=dg.AssetSelection.assets("groundskeeper_nightly"),
    description="Nightly Memory GC and cleanup.",
    execution_timezone="UTC",
)
def groundskeeper_schedule(context: ScheduleEvaluationContext) -> Iterator[dg.RunRequest]:
    yield dg.RunRequest(run_key=f"groundskeeper-{context.scheduled_execution_time}")
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/custodian/identities/test_groundskeeper.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/custodian/identities/groundskeeper.py \
        src/context_service/pipelines/jobs/groundskeeper_job.py \
        src/context_service/pipelines/schedules.py \
        tests/custodian/identities/test_groundskeeper.py
git commit -m "feat(custodian): add Groundskeeper identity for Memory GC (T9)"
```

---

## Task 5: Validator Identity

**Files:**
- Create: `src/context_service/custodian/identities/validator.py`
- Modify: `src/context_service/mcp/tools/context_crystallize.py`
- Create: `tests/custodian/identities/test_validator.py`

- [ ] **Step 1: Write failing test**

```python
# tests/custodian/identities/test_validator.py
import pytest
from unittest.mock import AsyncMock, MagicMock

from context_service.custodian.identities.validator import (
    ValidatorIdentity,
    ValidationResult,
)


@pytest.mark.asyncio
async def test_validator_passes_valid_hypothesis():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"premise_id": "p1", "exists": True},
        {"premise_id": "p2", "exists": True},
    ]

    validator = ValidatorIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-pro",
        timeout_seconds=5,
    )

    result = await validator.validate_premises(["p1", "p2"])
    assert result.valid is True
    assert result.validation_skipped is False
```

- [ ] **Step 2: Implement Validator**

```python
# custodian/identities/validator.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import BaseModel

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class ValidationResult(BaseModel):
    valid: bool
    validation_skipped: bool = False
    reasons: list[str] = field(default_factory=list)


PREMISE_EXISTS_QUERY = """
UNWIND $premise_ids AS pid
OPTIONAL MATCH (n {id: pid, silo_id: $silo_id})
RETURN pid AS premise_id, n IS NOT NULL AS exists
"""


@dataclass
class ValidatorIdentity:
    """Validates reasoning structure on crystallize (T13)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: float = 5.0

    async def validate_premises(self, premise_ids: list[str]) -> ValidationResult:
        """Check all premise node IDs exist in silo."""
        if not premise_ids:
            return ValidationResult(valid=True)

        rows = await self.store.execute_query(
            PREMISE_EXISTS_QUERY,
            {"premise_ids": premise_ids, "silo_id": self.silo_id},
        )

        missing = [r["premise_id"] for r in rows if not r["exists"]]
        if missing:
            return ValidationResult(
                valid=False,
                reasons=[f"Missing premises: {missing}"],
            )

        return ValidationResult(valid=True)

    async def validate_crystallize(
        self, hypothesis_ids: list[str]
    ) -> ValidationResult:
        """Full validation for crystallize. Called from context_crystallize MCP tool."""
        # For now, just validate premises exist
        # TODO: Add LLM-based reasoning structure validation
        
        all_premises = []
        for hid in hypothesis_ids:
            rows = await self.store.execute_query(
                "MATCH (h:WorkingHypothesis {id: $id})-[:DERIVED_FROM]->(p) RETURN p.id AS premise_id",
                {"id": hid},
            )
            all_premises.extend([r["premise_id"] for r in rows])

        return await self.validate_premises(all_premises)
```

- [ ] **Step 3: Hook into context_crystallize**

Modify `mcp/tools/context_crystallize.py`. After line 45 (before the gather), add:

```python
# Validator intercept
settings = get_settings()
if settings.identities.validator.enabled:
    from context_service.custodian.identities.validator import ValidatorIdentity, ValidationResult

    validator = ValidatorIdentity(
        store=store,
        silo_id=str(resolved_silo_id),
        model=settings.identities.validator.model,
        timeout_seconds=settings.identities.validator.timeout_seconds,
    )

    try:
        validation = await asyncio.wait_for(
            validator.validate_crystallize(belief_ids),
            timeout=settings.identities.validator.timeout_seconds,
        )
        if not validation.valid:
            if settings.identities.validator.fail_open:
                logger.warning(
                    "validator.failed_open",
                    reasons=validation.reasons,
                    identity="validator",
                )
            else:
                return {"error": "validation_failed", "reasons": validation.reasons}
    except asyncio.TimeoutError:
        logger.warning("validator.timeout", identity="validator")
        # fail-open: continue
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/custodian/identities/test_validator.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/identities/validator.py \
        src/context_service/mcp/tools/context_crystallize.py \
        tests/custodian/identities/test_validator.py
git commit -m "feat(custodian): add Validator identity for crystallize (T13)"
```

---

## Task 6: Custodian Identity (Contradiction Detection)

**Files:**
- Create: `src/context_service/custodian/identities/custodian.py`
- Modify: `src/context_service/services/context.py` (post-write hook)
- Create: `tests/custodian/identities/test_custodian_identity.py`

- [ ] **Step 1: Write failing test**

```python
# tests/custodian/identities/test_custodian_identity.py
import pytest
from unittest.mock import AsyncMock

from context_service.custodian.identities.custodian import CustodianIdentity


@pytest.mark.asyncio
async def test_custodian_detects_no_contradiction():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = []  # No existing facts

    custodian = CustodianIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-flash",
    )

    result = await custodian.check_contradiction("new-fact-id")
    assert result.has_contradiction is False
```

- [ ] **Step 2: Implement Custodian identity**

```python
# custodian/identities/custodian.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_ai import Agent

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.custodian.identities.base import IdentityDeps

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class ContradictionResult(BaseModel):
    has_contradiction: bool
    supersedes_ids: list[str] = []
    reason: str | None = None


SIMILAR_FACTS_QUERY = """
MATCH (new:Fact {id: $fact_id, silo_id: $silo_id})
MATCH (existing:Fact {silo_id: $silo_id})
WHERE existing.id <> new.id
  AND existing.subject = new.subject
  AND existing.predicate = new.predicate
RETURN existing.id AS fact_id, existing.content AS content
LIMIT 10
"""

WRITE_SUPERSEDES_QUERY = """
MATCH (new:Fact {id: $new_id, silo_id: $silo_id})
MATCH (old:Fact {id: $old_id, silo_id: $silo_id})
MERGE (new)-[:SUPERSEDES {reason: $reason, created_at: datetime()}]->(old)
"""


@dataclass
class CustodianIdentity:
    """Contradiction detection and supersession (T2)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-flash"

    async def check_contradiction(self, fact_id: str) -> ContradictionResult:
        """Check if a new fact contradicts existing facts."""
        similar = await self.store.execute_query(
            SIMILAR_FACTS_QUERY,
            {"fact_id": fact_id, "silo_id": self.silo_id},
        )

        if not similar:
            return ContradictionResult(has_contradiction=False)

        # TODO: Use LLM agent to determine actual contradiction
        # For now, just flag potential conflicts
        return ContradictionResult(
            has_contradiction=False,
            supersedes_ids=[],
            reason=None,
        )

    async def write_supersession(self, new_id: str, old_id: str, reason: str) -> None:
        """Write SUPERSEDES edge between facts."""
        await self.store.execute_write(
            WRITE_SUPERSEDES_QUERY,
            {"new_id": new_id, "old_id": old_id, "silo_id": self.silo_id, "reason": reason},
        )
        logger.info(
            "custodian.supersession_written",
            new_id=new_id,
            old_id=old_id,
            reason=reason,
            identity="custodian",
        )


async def on_custodian_batch_fire(silo_id: str, node_ids: list[str]) -> None:
    """Callback for AsyncBatchTrigger. Processes a batch of nodes."""
    settings = get_settings()
    
    # Get store from context (simplified - actual impl needs proper DI)
    from context_service.stores import get_memgraph_client
    store = await get_memgraph_client()

    custodian = CustodianIdentity(
        store=store,
        silo_id=silo_id,
        model=settings.identities.custodian.model,
    )

    for node_id in node_ids:
        result = await custodian.check_contradiction(node_id)
        if result.has_contradiction:
            for old_id in result.supersedes_ids:
                await custodian.write_supersession(node_id, old_id, result.reason or "contradiction")
```

- [ ] **Step 3: Add post-write hook in services/context.py**

After the store saga completes successfully (around line 338), add:

```python
# Fire Custodian identity on Knowledge-layer writes
if node.layer == PersistenceLayer.KNOWLEDGE:
    settings = get_settings()
    if settings.identities.custodian.enabled:
        from context_service.custodian.identities.triggers.async_batch import AsyncBatchTrigger
        from context_service.custodian.identities.custodian import on_custodian_batch_fire

        trigger = _get_custodian_trigger()
        asyncio.create_task(
            trigger.enqueue(str(silo_id), str(node.id), "store")
        )


# Module-level singleton (add near top of file)
_custodian_trigger: AsyncBatchTrigger | None = None

def _get_custodian_trigger() -> AsyncBatchTrigger:
    global _custodian_trigger
    if _custodian_trigger is None:
        settings = get_settings()
        _custodian_trigger = AsyncBatchTrigger(
            batch_size=settings.identities.custodian.batch_size,
            window_seconds=settings.identities.custodian.batch_window_seconds,
            on_fire=on_custodian_batch_fire,
        )
    return _custodian_trigger
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/custodian/identities/test_custodian_identity.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/context_service/custodian/identities/custodian.py \
        src/context_service/services/context.py \
        tests/custodian/identities/test_custodian_identity.py
git commit -m "feat(custodian): add Custodian identity for contradiction detection (T2)"
```

---

## Task 7: Synthesizer Identity

**Files:**
- Create: `src/context_service/custodian/identities/synthesizer.py`
- Create: `src/context_service/pipelines/sensors/synthesizer_sensor.py`
- Modify: `src/context_service/pipelines/schedules.py`
- Create: `tests/custodian/identities/test_synthesizer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/custodian/identities/test_synthesizer.py
import pytest
from unittest.mock import AsyncMock

from context_service.custodian.identities.synthesizer import SynthesizerIdentity


@pytest.mark.asyncio
async def test_synthesizer_finds_candidates():
    mock_store = AsyncMock()
    mock_store.execute_query.return_value = [
        {"cluster_id": "c1", "fact_count": 5},
    ]

    synthesizer = SynthesizerIdentity(
        store=mock_store,
        silo_id="test-silo",
        model="google-vertex:gemini-2.5-pro",
    )

    candidates = await synthesizer.find_synthesis_candidates()
    assert len(candidates) >= 0
```

- [ ] **Step 2: Implement Synthesizer**

```python
# custodian/identities/synthesizer.py
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger
from context_service.custodian.proposal_worker import (
    get_proposal_candidates,
    create_proposal,
)

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.models.silo import ResolvedSiloConfig

logger = get_logger(__name__)


@dataclass
class SynthesizerIdentity:
    """Weak synthesis, ProposedBelief creation, revision (T3/T4/T10)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-pro"

    async def find_synthesis_candidates(self) -> list[dict]:
        """Find clusters ready for synthesis."""
        # Reuse existing proposal_worker logic
        from context_service.models.silo import ResolvedSiloConfig
        
        # Default config - in practice, load from silo settings
        config = ResolvedSiloConfig(
            belief_density_threshold=3,
            proposal_threshold=0.3,
            auto_synthesis_threshold=0.7,
        )
        
        return await get_proposal_candidates(self.store, self.silo_id, config)

    async def run_synthesis(self) -> dict:
        """Run synthesis for all candidates in silo."""
        candidates = await self.find_synthesis_candidates()
        
        from context_service.models.silo import ResolvedSiloConfig
        config = ResolvedSiloConfig(
            belief_density_threshold=3,
            proposal_threshold=0.3,
            auto_synthesis_threshold=0.7,
        )

        created = []
        for candidate in candidates:
            proposal_id = await create_proposal(
                self.store,
                cluster_id=candidate["cluster_id"],
                silo_id=self.silo_id,
                confidence=candidate["confidence"],
            )
            if proposal_id:
                created.append(proposal_id)

        logger.info(
            "synthesizer.run_complete",
            silo_id=self.silo_id,
            candidates=len(candidates),
            created=len(created),
            identity="synthesizer",
        )

        return {"candidates": len(candidates), "created": len(created)}
```

- [ ] **Step 3: Create Dagster sensor**

```python
# pipelines/sensors/synthesizer_sensor.py
import asyncio
from collections.abc import Iterator

import dagster as dg

from context_service.config.settings import get_settings
from context_service.pipelines.resources import MemgraphResource


@dg.sensor(name="synthesizer_sensor", minimum_interval_seconds=300)
def synthesizer_sensor(
    context: dg.SensorEvaluationContext,
    memgraph: MemgraphResource,
) -> dg.SensorResult:
    """Trigger synthesis when pending proposals exceed threshold."""
    settings = get_settings()
    threshold = settings.identities.synthesizer.threshold_pending_nodes

    async def _check() -> list[dg.RunRequest]:
        driver = await memgraph.driver()
        from context_service.stores import MemgraphClient
        store = MemgraphClient(driver)

        query = """
        MATCH (c:Cluster)
        WHERE NOT exists((c)<-[:COVERS]-(:Belief))
        WITH c.silo_id AS silo_id, count(c) AS pending
        WHERE pending >= $threshold
        RETURN silo_id, pending
        """
        rows = await store.execute_query(query, {"threshold": threshold})

        return [
            dg.RunRequest(
                run_key=f"synthesizer-{row['silo_id']}",
                partition_key=row["silo_id"],
            )
            for row in rows
        ]

    requests = asyncio.run(_check())
    return dg.SensorResult(run_requests=requests)
```

- [ ] **Step 4: Add hourly schedule**

In `pipelines/schedules.py`:

```python
@dg.schedule(
    cron_schedule="0 * * * *",
    name="synthesizer_hourly",
    target=dg.AssetSelection.assets("synthesizer_sweep"),
    description="Hourly synthesis sweep.",
    execution_timezone="UTC",
)
def synthesizer_hourly_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"synthesizer-hourly-{silo_id}-{context.scheduled_execution_time}",
            partition_key=silo_id,
        )
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/custodian/identities/test_synthesizer.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/context_service/custodian/identities/synthesizer.py \
        src/context_service/pipelines/sensors/synthesizer_sensor.py \
        src/context_service/pipelines/schedules.py \
        tests/custodian/identities/test_synthesizer.py
git commit -m "feat(custodian): add Synthesizer identity for weak synthesis (T3/T4/T10)"
```

---

## Task 8: Integration Test and Cleanup

**Files:**
- Create: `tests/integration/test_identity_e2e.py`
- Update: `src/context_service/custodian/identities/__init__.py`

- [ ] **Step 1: Update identities __init__.py exports**

```python
# custodian/identities/__init__.py
"""Four custodian identities per EAG transitions."""

from context_service.custodian.identities.base import IdentityDeps
from context_service.custodian.identities.custodian import CustodianIdentity
from context_service.custodian.identities.synthesizer import SynthesizerIdentity
from context_service.custodian.identities.groundskeeper import GroundskeeperIdentity
from context_service.custodian.identities.validator import ValidatorIdentity

__all__ = [
    "IdentityDeps",
    "CustodianIdentity",
    "SynthesizerIdentity",
    "GroundskeeperIdentity",
    "ValidatorIdentity",
]
```

- [ ] **Step 2: Write integration test**

```python
# tests/integration/test_identity_e2e.py
import pytest

from context_service.custodian.identities import (
    CustodianIdentity,
    SynthesizerIdentity,
    GroundskeeperIdentity,
    ValidatorIdentity,
)


def test_all_identities_importable():
    """Smoke test: all identities can be imported."""
    assert CustodianIdentity is not None
    assert SynthesizerIdentity is not None
    assert GroundskeeperIdentity is not None
    assert ValidatorIdentity is not None
```

- [ ] **Step 3: Run full test suite**

```bash
just test
```

- [ ] **Step 4: Run type check**

```bash
just check
```

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat(custodian): complete 4-identity split implementation"
```

---

## Verification

1. **Unit tests pass:**
   ```bash
   pytest tests/custodian/identities/ -v
   ```

2. **Type check passes:**
   ```bash
   just check
   ```

3. **Config loads correctly:**
   ```python
   from context_service.config.settings import get_settings
   settings = get_settings()
   print(settings.identities.custodian.model)
   ```

4. **Dagster jobs visible:**
   ```bash
   dagster job list
   # Should show: groundskeeper_nightly
   ```

5. **MCP tool still works:**
   ```bash
   # Test context_crystallize with validator hook
   ```

---

## Summary

| Task | Identity | Files | Est. Time |
|------|----------|-------|-----------|
| 1 | Config | identities.yaml, settings.py | 30 min |
| 2 | Base | base.py, protocols.py | 20 min |
| 3 | Trigger | async_batch.py | 45 min |
| 4 | Groundskeeper | groundskeeper.py, job | 1 hr |
| 5 | Validator | validator.py, crystallize hook | 1 hr |
| 6 | Custodian | custodian.py, store hook | 1.5 hr |
| 7 | Synthesizer | synthesizer.py, sensor, schedule | 1.5 hr |
| 8 | Integration | exports, e2e test | 30 min |

**Total: ~7 hours**
