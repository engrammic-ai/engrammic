# Phase 9: Complete Dagster Migration

**Status:** COMPLETE  
**Depends on:** Phase 8 (Reactions Infrastructure) - COMPLETE  
**Date:** 2026-06-02  
**Branch:** `feat/brain-architecture`  
**Completed:** 2026-06-02

---

## Goal

Complete the migration from Dagster-based batch processing to Taskiq event-driven workers. Remove redundant Dagster jobs while keeping Dagster for orchestration visibility and scheduled maintenance tasks.

---

## Background

Phase 8 shipped:
- Taskiq broker with silo-partitioned queues
- 8 reaction task handlers (all now implemented)
- Transaction integration (emit_reaction on all writes)
- Worker deployment (docker-compose)
- Queue health monitoring sensors

This phase completes the migration by:
1. Implementing the stub handlers
2. Wiring remaining infrastructure (Qdrant)
3. Disabling overlapping Dagster jobs
4. Cleaning up dead code

---

## Task 1: Complete Stub Handlers

**Files:** `reactions/tasks.py`

Three handlers are stubs that log "not yet implemented":

### 1.1 update_cluster_membership

Current: Stub  
Target: Assign node to appropriate cluster based on embedding similarity

```python
async def update_cluster_membership_task(node_id: str, silo_id: str, **payload):
    # 1. Get node embedding from Qdrant
    # 2. Find nearest cluster centroid
    # 3. Update node's cluster_id in Memgraph
    # 4. If cluster grew past threshold, emit check_synthesis
```

Depends on: Qdrant vector store access in worker context

### 1.2 check_synthesis

Current: Stub  
Target: Check if cluster is ready for synthesis, trigger if so

```python
async def check_synthesis_task(node_id: str, silo_id: str, **payload):
    cluster_id = payload.get("cluster_id")
    # 1. Count active nodes in cluster
    # 2. Check cluster state (READY, not SYNTHESIZED)
    # 3. If count >= SYNTHESIS_THRESHOLD, call synthesize()
```

Depends on: `sage.transactions.synthesize()` already exists

### 1.3 propagate_confidence

Current: Stub  
Target: Run incremental confidence propagation from a node

```python
async def propagate_confidence_task(node_id: str, silo_id: str, **payload):
    # 1. Get node's neighborhood (depth 2)
    # 2. Call propagate_incremental() from sage.epistemology
    # 3. Emit cascade events for affected nodes if confidence changed significantly
```

Depends on: `sage.epistemology.propagate_incremental()` from Phase 7

---

## Task 2: Wire Qdrant Vector Store

**Files:** `reactions/tasks.py`, `reactions/worker.py`

The `compute_embedding` handler embeds content but can't upsert to Qdrant because the worker doesn't have access to `EngineQdrantStore`.

### 2.1 Add vector store to worker context

```python
# worker.py
from context_service.stores.vector import get_vector_store

@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def startup(state: TaskiqState):
    state.vector_store = get_vector_store()
```

### 2.2 Complete compute_embedding handler

```python
async def compute_embedding_task(node_id: str, silo_id: str, **payload):
    # Current: embeds content, logs vector length
    # Add: upsert to Qdrant via state.vector_store
    vector_store = get_vector_store(silo_id)
    await vector_store.upsert(node_id, embedding, metadata)
```

---

## Task 3: Disable Dagster Job Scheduling

**Files:** `pipelines/schedules.py`, `pipelines/jobs/`

### 3.1 Identify overlapping jobs

| Dagster Job | Replacement | Action |
|-------------|-------------|--------|
| `custodian_embedding_job` | `compute_embedding` task | Disable schedule |
| `custodian_clustering_job` | `update_cluster_membership` task | Disable schedule |
| `synthesizer_job` | `check_synthesis` + `consolidate` tasks | Disable schedule |
| `groundskeeper_job` | Keep (cleanup tasks not event-driven) | No change |
| `validator_job` | Keep (periodic validation) | No change |

### 3.2 Disable schedules

```python
# schedules.py
# Comment out or remove:
# @schedule(cron_schedule="*/5 * * * *", job=custodian_embedding_job)
# def custodian_embedding_schedule(): ...
```

### 3.3 Keep monitoring

The reaction health sensors continue to run, monitoring queue depth and DLQ.

---

## Task 4: Remove Dead Code

**Files:** Various in `pipelines/`, `custodian/`

After confirming workers handle all events:

### 4.1 Remove disabled Dagster jobs

- `pipelines/jobs/custodian_embedding.py`
- `pipelines/jobs/custodian_clustering.py`
- `pipelines/jobs/synthesizer.py`

### 4.2 Clean up unused custodian code

- Review `custodian/` for functions only called from removed jobs
- Keep shared utilities used by remaining jobs or tasks

### 4.3 Update definitions.py

Remove references to deleted jobs from Dagster definitions.

---

## Task 5: Task Queue Abstraction (Phase 8b)

**Files:** New `src/context_service/tasks/` module

Per Phase 8 sub-plan, abstract Taskiq behind a generic interface:

### 5.1 Interface

```python
# tasks/base.py
class TaskBackend(ABC):
    async def enqueue(self, task_name: str, args, kwargs, options) -> str
    async def get_result(self, task_id: str, timeout: float) -> Any
    def task(self, name: str, options: TaskOptions) -> Callable
```

### 5.2 Implementations

- `TaskiqBackend` - wraps current broker
- `SyncBackend` - inline execution for tests
- `MemoryBackend` - in-memory queue for dev

### 5.3 Refactor reactions

Update `reactions/` to use the abstraction instead of direct Taskiq calls.

---

## Task 6: Production Deployment

### 6.1 Deploy workers to beta

```bash
# On beta stateful host
docker-compose -f docker-compose.prod.yml up -d reaction-worker
```

### 6.2 Monitor queue health

- Watch Dagster sensors for queue depth
- Check DLQ for failed tasks
- Verify task processing latency

### 6.3 Gradual rollout

1. Deploy workers (parallel with Dagster)
2. Monitor for 24h
3. Disable Dagster schedules
4. Monitor for 24h
5. Remove Dagster jobs

---

## Task 7: Tests

- [x] Integration tests for completed stub handlers
- [x] End-to-end test: write -> emit -> process -> verify state
- [x] Test worker startup/shutdown with vector store
- [x] Test cluster membership assignment
- [x] Test synthesis triggering

---

## Success Criteria

1. All 8 task handlers fully implemented
2. No overlapping Dagster jobs running
3. Queue depth stays under threshold in steady state
4. DLQ empty (all tasks succeed or are triaged)
5. Task processing latency meets targets from Phase 8

---

## Rollback Plan

If workers fail in production:
1. Re-enable Dagster schedules (immediate)
2. Scale down worker replicas
3. Investigate failures from DLQ
4. Fix and redeploy

The dual-running period (Phase 8a) ensures Dagster can take over if needed.

---

## Out of Scope

- Multi-region event routing
- Event replay UI
- Priority queues
- Auto-scaling workers based on queue depth
