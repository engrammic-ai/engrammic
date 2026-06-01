# Phase 8: Reactions Infrastructure

**Status:** COMPLETE (2026-06-02)

**Goal:** Replace cadence-based Dagster jobs with event-driven Taskiq workers while keeping Dagster for orchestration visibility.

**Date:** 2026-06-02  
**Branch:** `feat/brain-architecture`

---

## Completion Summary

**Commits:** 10 (a6c4311..41b2c5d)  
**Tests:** 51 passing  
**Files added:** 2,892 lines across reactions/, sensors/, tests/

### What shipped:
- `reactions/broker.py` - Silo-partitioned Taskiq broker with SmartRetryMiddleware + DeadLetterMiddleware
- `reactions/events.py` - ReactionEventType enum (11 types), ReactionEvent dataclass, emit_reaction() fire-and-forget helper
- `reactions/tasks.py` - 8 task handlers (5 fully implemented, 3 stubs for Phase 9)
- `reactions/worker.py` - LoggingMiddleware, TracingMiddleware, Sentry integration, health check task
- `reactions/worker_entrypoint.py` - CLI entrypoint for `taskiq worker`
- `pipelines/sensors/reaction_health.py` - Queue depth + DLQ monitoring sensors
- `sage/transactions.py` - All 11 transaction functions now emit reactions directly (emit=True flag)
- Docker deployment: reaction-worker service in dev and prod compose files

### Handler status:
| Handler | Status |
|---------|--------|
| compute_embedding | Implemented (Qdrant upsert pending vector store wiring) |
| update_heat | Fully implemented |
| cascade_staleness | Fully implemented |
| flag_contradiction | Implemented (emits consolidate) |
| consolidate | Fully implemented |
| update_cluster_membership | Stub (Phase 9) |
| check_synthesis | Stub (Phase 9) |
| propagate_confidence | Stub (Phase 9) |

### Open items for Phase 9:
1. Complete stub handlers (cluster membership, synthesis, confidence propagation)
2. Wire Qdrant vector store into compute_embedding handler
3. Disable Dagster job scheduling (workers take over)
4. Remove legacy Dagster jobs
5. Task queue abstraction (Phase 8b sub-plan)

---

## Architecture

```
Transaction (write) 
    |
    v
ReactionEvent emitted --> Redis Stream (silo-partitioned)
                              |
                              v
                         Taskiq Worker Pool
                              |
                              v
                         Process reaction (consolidate, cascade, cluster, etc.)
                              |
                              v
                         Dagster sensors monitor queue health
```

**Key decisions:**
1. **Taskiq** for async workers - native asyncio, FastAPI integration, actively maintained
2. **Redis Streams** as broker - already in stack, silo-partitioned for tenant isolation
3. **Dagster sensors** for monitoring - queue depth, dead letters, worker health
4. Keep existing Dagster jobs as fallback during migration (remove in Phase 9)

---

## Dependencies

Add to pyproject.toml:
```toml
taskiq = { version = "^0.11", extras = ["redis"] }
taskiq-redis = "^1.0"
```

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/reactions/broker.py` | Taskiq broker setup, silo-partitioned queues |
| `src/context_service/reactions/tasks.py` | Task definitions (consolidate, cascade, cluster, etc.) |
| `src/context_service/reactions/worker.py` | Worker configuration, middleware, error handling |
| `src/context_service/reactions/events.py` | ReactionEvent schema, emit helpers |
| `src/context_service/reactions/__init__.py` | Public API |
| `src/context_service/pipelines/sensors/reaction_health.py` | Dagster sensor for queue monitoring |
| `tests/reactions/` | Unit and integration tests |

---

## Task 1: Broker Setup

**Files:** `reactions/broker.py`

- [x] Configure Taskiq Redis broker with silo-partitioned queue names
- [x] Add connection pooling (reuse existing Redis from config)
- [x] Add retry policy (exponential backoff, max 3 retries)
- [x] Add dead letter queue for failed tasks

```python
from taskiq_redis import ListQueueBroker

def get_broker(silo_id: str) -> ListQueueBroker:
    return ListQueueBroker(
        url=settings.redis_url,
        queue_name=f"reactions:{silo_id}",
    )
```

---

## Task 2: Event Schema and Emission

**Files:** `reactions/events.py`, update `sage/transactions.py`

Current `ReactionEvent` in transactions.py:
```python
@dataclass
class ReactionEvent:
    event_type: str
    node_id: str
    silo_id: str
    payload: dict[str, Any] = field(default_factory=dict)
```

- [x] Move to `reactions/events.py`
- [x] Add `emit_reaction()` helper that enqueues to Taskiq
- [x] Add event type enum for type safety
- [x] Wire into transaction return paths (replace list accumulation with direct emit)

---

## Task 3: Task Definitions

**Files:** `reactions/tasks.py`

Migrate reaction handlers from current inline/Dagster code:

| Event Type | Handler | Current Location |
|------------|---------|------------------|
| `compute_embedding` | Embed node content, upsert to vector store | Dagster custodian |
| `update_heat` | Increment heat score | Inline in transactions |
| `update_cluster_membership` | Assign node to cluster | Dagster custodian |
| `cascade_staleness` | Mark dependents stale | `sage/transactions.py` |
| `flag_contradiction` | Queue for consolidation | `sage/transactions.py` |
| `consolidate` | Run consolidation worker | Dagster synthesizer |
| `check_synthesis` | Trigger lazy synthesis if ready | Dagster synthesizer |
| `propagate_confidence` | Run incremental propagation | New in Phase 7 |

- [x] Define Taskiq tasks for each event type
- [x] Add timeout and retry config per task type
- [x] Add structured logging with trace IDs

---

## Task 4: Worker Configuration

**Files:** `reactions/worker.py`

- [x] Configure worker pool size (default: 4 workers)
- [x] Add graceful shutdown handling
- [x] Add middleware for:
  - Structured logging (structlog integration)
  - OpenTelemetry tracing
  - Error capture (Sentry if configured)
- [x] Add health check endpoint

---

## Task 5: Transaction Integration

**Files:** `sage/transactions.py`

Currently transactions return `list[ReactionEvent]`. Change to emit directly:

- [x] Replace event accumulation with `await emit_reaction(event)`
- [x] Make emission async but non-blocking (fire-and-forget with timeout)
- [x] Add fallback to sync processing if Redis unavailable
- [x] Keep event list return for testing (mock emit)

---

## Task 6: Dagster Monitoring

**Files:** `pipelines/sensors/reaction_health.py`

- [x] Sensor to check queue depths per silo
- [x] Alert on queue backlog > threshold (configurable)
- [x] Sensor to check dead letter queue
- [ ] Dashboard asset for reaction metrics (deferred)

Keep existing Dagster jobs running in parallel during migration.

---

## Task 7: Worker Deployment

**Files:** `Dockerfile`, `docker-compose.yml`, deployment configs

- [x] Add `taskiq worker` command to Dockerfile
- [x] Add worker service to docker-compose
- [x] Configure worker count per environment (dev: 1, beta: 2, prod: 4)
- [ ] Add worker to Pulumi/deployment (deferred - manual deploy first)

---

## Task 8: Tests

- [x] Unit tests for task handlers (mock store/services)
- [x] Integration test for emit -> process flow
- [x] Test retry behavior
- [x] Test dead letter handling
- [x] Test silo isolation (events don't cross silos)

---

## Migration Strategy

1. **Phase 8a:** Deploy workers alongside Dagster jobs (both process events)
2. **Phase 8b:** Disable Dagster job scheduling, workers take over
3. **Phase 9:** Remove Dagster jobs entirely

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Event emit latency | < 5ms (async, non-blocking) |
| Task pickup latency | < 50ms |
| Consolidation task | < 5s (LLM bound) |
| Embedding task | < 500ms |
| Queue depth (steady state) | < 100 per silo |

---

## Out of Scope (Phase 8)

- Multi-region event routing (post-GTM)
- Event replay/reprocessing UI (use Redis CLI for now)
- Priority queues (all events equal priority for now)

---

## Sub-plan: Task Queue Abstraction (Phase 8b)

**Goal:** Abstract Taskiq behind a generic interface for broader adoption across the codebase.

### Rationale

Phase 8 core focuses on reactions. But we'll want background tasks elsewhere:
- Scheduled reports/exports
- Bulk operations (batch delete, migrations)
- Webhook delivery
- LLM calls that can be deferred

An abstraction lets us:
1. Swap backends without touching call sites
2. Provide consistent retry/timeout/logging behavior
3. Enable sync fallback for testing or degraded mode

### Interface Design

```python
# src/context_service/tasks/base.py

from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar
from dataclasses import dataclass

T = TypeVar("T")

@dataclass
class TaskOptions:
    timeout_seconds: float = 300
    max_retries: int = 3
    retry_delay_seconds: float = 5
    queue: str = "default"

class TaskBackend(ABC):
    @abstractmethod
    async def enqueue(
        self,
        task_name: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        options: TaskOptions | None = None,
    ) -> str:
        """Enqueue task, return task ID."""
        ...

    @abstractmethod
    async def get_result(self, task_id: str, timeout: float = 30) -> Any:
        """Wait for and return task result."""
        ...

    @abstractmethod
    def task(
        self,
        name: str | None = None,
        options: TaskOptions | None = None,
    ) -> Callable[[Callable[..., T]], Callable[..., T]]:
        """Decorator to register a task."""
        ...

class TaskQueue:
    """Facade for task operations."""
    
    def __init__(self, backend: TaskBackend):
        self._backend = backend
    
    async def enqueue(self, task_name: str, *args, **kwargs) -> str:
        return await self._backend.enqueue(task_name, args, kwargs)
    
    def task(self, name: str | None = None, **opts):
        return self._backend.task(name, TaskOptions(**opts))
```

### Implementations

| File | Backend |
|------|---------|
| `tasks/backends/taskiq_backend.py` | Taskiq (production) |
| `tasks/backends/sync_backend.py` | Sync/inline (testing, fallback) |
| `tasks/backends/memory_backend.py` | In-memory queue (dev) |

### File Structure Addition

```
src/context_service/tasks/
    __init__.py          # Public API: get_task_queue()
    base.py              # Abstract interface
    backends/
        __init__.py
        taskiq_backend.py
        sync_backend.py
        memory_backend.py
```

### Usage Example

```python
from context_service.tasks import get_task_queue

queue = get_task_queue()

@queue.task(name="send_webhook", timeout_seconds=30)
async def send_webhook(url: str, payload: dict) -> bool:
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload)
        return resp.is_success

# Enqueue from anywhere
await send_webhook.enqueue("https://example.com/hook", {"event": "created"})
```

### Migration Path

1. **Phase 8 core:** Reactions use Taskiq directly (simpler, fewer abstractions)
2. **Phase 8b:** Introduce abstraction, refactor reactions to use it
3. **Post-Phase 8:** Adopt for other background work (webhooks, exports, etc.)

### Tasks (Phase 8b)

- [ ] Define `TaskBackend` ABC and `TaskOptions`
- [ ] Implement `TaskiqBackend` wrapping current broker setup
- [ ] Implement `SyncBackend` for tests
- [ ] Implement `MemoryBackend` for dev
- [ ] Add `get_task_queue()` factory with config-based backend selection
- [ ] Refactor reactions to use abstraction
- [ ] Documentation and usage examples

---

## Open Questions

1. **Silo discovery:** How do workers know which silos exist? Options:
   - Static config
   - Query DB for active silos
   - One worker pool per silo (more isolation, more resources)

2. **Backpressure:** If workers fall behind, should transactions block or drop events?
   - Recommend: async emit with short timeout, log warning on failure

3. **Idempotency:** Are all handlers idempotent? Need audit.
