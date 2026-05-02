# Critical Performance Fixes

**Status:** Complete  
**Created:** 2026-05-01  
**Completed:** 2026-05-01  
**Priority:** Critical (blocks p95 targets)

## Context

Review identified 4 performance issues causing latency well above p95 targets (< 300ms for writes). These should be addressed before scaling/resilience work since they affect baseline performance.

## Problems

### 1. N+1 Writes in Claim Ingestion
**Location:** `extraction/service.py:354-416`

`apply_claims_to_graph()` loops through triples sequentially, issuing separate `execute_write()` calls for each claim, attachment, entity mention, and doc reference.

**Impact:** 100 claims with 3 mentions = 600+ round trips. Dominates ingest latency.

### 2. Unbatched HyperEdge Participants
**Location:** `engine/memgraph_store.py:629-655`

`upsert_hyperedge()` does 1 write for node, 1 for delete, then N writes in loop for participants.

**Impact:** Each hyperedge with M participants = 2+M round trips.

### 3. stdlib json on Hot Paths
**Location:** 67 instances across codebase (primarily `engine/`, `mcp/`)

Uses stdlib `json.loads/json.dumps` for parameter serialization in query loops.

**Impact:** Blocks event loop; 5-10x slower than orjson on large property dicts.

### 4. Fixed Memgraph Pool Size
**Location:** `stores/memgraph.py:88`

Hardcoded pool of 50 connections with 30s acquisition timeout.

**Impact:** Under concurrent load, pool exhaustion causes p95 spikes.

---

## Implementation Plan

### Phase 1: Batch Database Writes (Highest impact)

#### 1.1 Batch claim ingestion with UNWIND
- Refactor `apply_claims_to_graph()` to collect all operations
- Build single Cypher query using UNWIND for claims, attachments, mentions
- Single transaction per batch instead of N transactions

#### 1.2 Batch hyperedge participants
- Refactor `upsert_hyperedge()` to use UNWIND for participant creation
- Single query: create node + delete old + create all new participants

### Phase 2: JSON Serialization (Quick win)

#### 2.1 Replace stdlib json with orjson
- Add `orjson` to dependencies
- Create `src/context_service/utils/json.py` with `dumps`/`loads` wrappers
- Replace all `json.loads`/`json.dumps` imports across codebase
- Verify structlog uses orjson processor

### Phase 3: Connection Pool Tuning (Config change)

#### 3.1 Make pool size configurable
- Add `MEMGRAPH_POOL_SIZE` and `MEMGRAPH_POOL_TIMEOUT` to settings
- Default to 50/30s but allow override via env
- Add pool metrics logging on acquisition timeout

---

## Verification

- [ ] Ingest 100 claims, measure round trips (target: < 10)
- [ ] Benchmark json vs orjson on typical property dict (target: 5x improvement)
- [ ] Load test with 20 concurrent MCP requests, verify no pool exhaustion
- [ ] Run `just check` - lint + typecheck pass

## Execution Order

1. **Performance (this plan)** - fixes baseline latency
2. **Scaling/resilience** - adds fault tolerance on top of fast baseline
