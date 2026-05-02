# Critical Performance Fixes

**Status:** Complete  
**Created:** 2026-05-01  
**Completed:** 2026-05-01  
**Verified:** 2026-05-03  
**Priority:** Critical (blocks p95 targets)

## Context

Review identified 4 performance issues causing latency well above p95 targets (< 300ms for writes). These should be addressed before scaling/resilience work since they affect baseline performance.

## Resolution Summary (2026-05-03)

| Issue | Status | Notes |
|-------|--------|-------|
| N+1 claim ingestion | Done | UNWIND batching in `db/queries.py:522-567` |
| Unbatched hyperedge | Deferred | `upsert_hyperedge` not called in production yet |
| stdlib json | Done | `utils/json.py` wraps orjson; 1 stdlib import remains (`json_repair`) |
| Fixed pool size | Done | Configurable via `memgraph_pool_size`/`memgraph_pool_timeout` settings |

---

## Original Problems

### 1. N+1 Writes in Claim Ingestion
**Location:** `extraction/service.py:354-416`

`apply_claims_to_graph()` loops through triples sequentially, issuing separate `execute_write()` calls for each claim, attachment, entity mention, and doc reference.

**Impact:** 100 claims with 3 mentions = 600+ round trips. Dominates ingest latency.

**Resolution:** Batched with UNWIND queries: `BATCH_UPSERT_CLAIMS`, `BATCH_UPSERT_ENTITY_MENTIONS`, `BATCH_ATTACH_CLAIMS_TO_PASSAGE`, `BATCH_ATTACH_CLAIM_REFERENCES`. Collapses N*4 RTTs to exactly 4 per batch.

### 2. Unbatched HyperEdge Participants
**Location:** `engine/memgraph_store.py:629-655`

`upsert_hyperedge()` does 1 write for node, 1 for delete, then N writes in loop for participants.

**Impact:** Each hyperedge with M participants = 2+M round trips.

**Resolution:** Deferred. The `upsert_hyperedge` method exists but is not called anywhere in production code yet. The query already UNWINDs participants within a single hyperedge; batch multi-hyperedge API can be added when the feature ships.

### 3. stdlib json on Hot Paths
**Location:** 67 instances across codebase (primarily `engine/`, `mcp/`)

Uses stdlib `json.loads/json.dumps` for parameter serialization in query loops.

**Impact:** Blocks event loop; 5-10x slower than orjson on large property dicts.

**Resolution:** `src/context_service/utils/json.py` provides orjson-backed `dumps`/`loads`. All hot paths migrated. Only remaining stdlib import is `json_repair` (external dep).

### 4. Fixed Memgraph Pool Size
**Location:** `stores/memgraph.py:88`

Hardcoded pool of 50 connections with 30s acquisition timeout.

**Impact:** Under concurrent load, pool exhaustion causes p95 spikes.

**Resolution:** Now uses `settings.memgraph_pool_size` and `settings.memgraph_pool_timeout`. Defaults unchanged (50/30s) but configurable via env. Pool acquisition timeout logged.

---

## Verification

- [x] Claim ingestion uses UNWIND batching (4 queries per batch)
- [x] orjson wrapper in place, hot paths migrated
- [x] Pool size/timeout configurable via settings
- [x] `just check` passes

## Execution Order

1. **Performance (this plan)** - fixes baseline latency
2. **Scaling/resilience** - adds fault tolerance on top of fast baseline
