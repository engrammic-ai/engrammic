# Hybrid Storage Implementation Complete

**Date:** 2026-05-05  
**Branch:** feature/hybrid-storage-spec  
**Status:** All 15 tasks complete

## Summary

Implemented hybrid Memgraph + Postgres storage for reasoning chains. Steps are stored in Postgres for durability; summary projections go to Memgraph for graph traversal.

## Changes

### Core Implementation

- **ChainSagaWriter** (`engine/chain_saga.py`): Postgres-first saga with compensation. Writes steps to Postgres, then summary to Memgraph. On Memgraph failure, rolls back Postgres row or dead-letters to `orphaned_chains`.

- **PostgresStore** (`engine/postgres_store.py`): Repository layer for `reasoning_chain_steps` and `orphaned_chains` tables. Includes batch fetch for `context_recall` performance.

- **Consolidation** (`custodian/consolidation.py`): Merges multiple conclusions with same `query_context_hash` into canonical form. Redis locks prevent races. 30s TTL (increased from 10s).

- **Dispatch integration** (`custodian/dispatch.py`): Added `dispatch_task_with_consolidation` wrapper that runs consolidation post-pass every 50 dispatches.

- **Reconciliation GC** (`pipelines/assets/reconciliation_gc.py`): Dagster asset on 15-min schedule. Re-reconciles orphaned chains, archives permanently failing rows, cleans dangling Postgres data.

### API Wiring

- **context_store**: Wired `conclusion` and `evidence_used` through saga to Memgraph. Added crystallization support (creates Knowledge-layer claims from reasoning).

- **context_recall**: Added `include_steps` parameter. When true, fetches steps from Postgres and attaches to intelligence-layer nodes.

### Bug Fixes (from review)

- Fixed 4 critical tenant isolation bugs in Cypher queries (missing `silo_id` in MERGE keys and edge queries)
- Fixed `GET_CHAIN_FOR_COMPACTION` to use summary fields instead of `steps` (which moved to Postgres)
- Added asyncio lock to prevent `get_session` init race
- Removed duplicate index on `ReasoningChainSteps.silo_id`

## Crystallization Optimization

Current implementation uses parallel claim creation + batch edge write:

```python
# Parallel: N claims created concurrently
results = await asyncio.gather(*[create_claim(c) for c in parsed_cryst])

# Batch: Single UNWIND query for all edges
await store.execute_write(BATCH_CREATE_CRYSTALLIZES_EDGES, {"edges": edges})
```

**Performance:** O(max(T)) + O(1) instead of O(N*T) + O(N)

### Future Optimizations (if needed)

1. **Background queue**: Push crystallizations to Redis/Dagster, return immediately. Response would include `crystallizations_pending: N` instead of `crystallized_claim_ids`. Most scalable but adds eventual consistency.

2. **Batch claim upsert**: New `batch_assert_claims` method using single UNWIND Cypher. Would reduce N round-trips to 1 for claim creation. Requires adding method to ContextService.

3. **Streaming crystallization**: For very large crystallization sets (100+), stream results via SSE or websocket. Unlikely to be needed in practice.

## Test Coverage

- 13 integration tests in `tests/integration/test_hybrid_storage.py`
- Covers saga write path, compensation, context_recall with steps, consolidation
- Unit tests updated for new methods and schedule count

## Files Changed

### Source
- `engine/chain_saga.py` - saga pattern
- `engine/postgres_store.py` - Postgres repository
- `engine/memgraph_store.py` - upsert_reasoning_chain
- `engine/protocols.py` - protocol updates
- `db/queries.py` - Cypher queries + tenant fixes
- `db/postgres.py` - init lock fix
- `custodian/consolidation.py` - conclusion consolidator
- `custodian/dispatch.py` - consolidation integration
- `mcp/tools/context_store.py` - conclusion/evidence/crystallization wiring
- `mcp/tools/context_recall.py` - include_steps
- `models/postgres/reasoning.py` - index fix
- `pipelines/assets/reconciliation_gc.py` - GC asset (new)
- `pipelines/schedules.py` - GC schedule

### Tests
- `tests/integration/test_hybrid_storage.py` (new)
- `tests/fakes/fake_graph_store.py`
- `tests/test_*.py` updates
