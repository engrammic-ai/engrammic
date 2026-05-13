# Telemetry Expansion Implementation Plan

**Status:** Complete  
**Created:** 2026-05-11  
**Completed:** 2026-05-13  
**Scope:** Add comprehensive metrics to all storage backends, LLM token tracking, reasoning chain reuse, and context_recall response sizing.

## Phase 1: New Metrics Infrastructure (metrics.py)

Add new instruments and recording functions to `src/context_service/telemetry/metrics.py`.

### 1.1 New Instruments (after line 26)

```python
_llm_token_counter: metrics.Counter | None = None
_reasoning_chain_reuse: metrics.Counter | None = None
_context_recall_size: metrics.Histogram | None = None
```

### 1.2 Initialize in setup_metrics() (after line 93)

```python
_llm_token_counter = _meter.create_counter(
    name="llm.tokens",
    description="LLM token usage",
    unit="1",
)

_reasoning_chain_reuse = _meter.create_counter(
    name="reasoning.chain.reuse",
    description="Reasoning chain cache hits/misses",
    unit="1",
)

_context_recall_size = _meter.create_histogram(
    name="context.recall.size",
    description="Context recall response size",
    unit="bytes",
)
```

### 1.3 New Recording Functions (after line 143)

```python
def record_llm_tokens(model: str, input_tokens: int, output_tokens: int) -> None:
    """Record LLM token usage."""
    if _llm_token_counter is None:
        return
    _llm_token_counter.add(input_tokens, {"model": model, "type": "input"})
    _llm_token_counter.add(output_tokens, {"model": model, "type": "output"})


def record_reasoning_chain_reuse(hit: bool) -> None:
    """Record reasoning chain cache hit/miss."""
    if _reasoning_chain_reuse is None:
        return
    _reasoning_chain_reuse.add(1, {"hit": str(hit).lower()})


def record_context_recall_size(layer: str, bytes_size: int, estimated_tokens: int) -> None:
    """Record context recall response size for token estimation."""
    if _context_recall_size is None:
        return
    _context_recall_size.record(bytes_size, {"layer": layer, "estimated_tokens": str(estimated_tokens)})
```

---

## Phase 2: Database Instrumentation

Add `record_db_query` calls to all uninstrumented store methods. Pattern:

```python
import time
from context_service.telemetry.metrics import record_db_query

start = time.perf_counter()
# ... actual operation ...
record_db_query("operation_name", (time.perf_counter() - start) * 1000)
```

### 2.1 stores/qdrant.py (6 methods)

| Method | Line | Operation Name |
|--------|------|----------------|
| `ensure_collection` | ~45 | `qdrant.ensure_collection` |
| `health_check` | ~60 | `qdrant.health_check` |
| `upsert` | ~75 | `qdrant.upsert` |
| `search` | ~95 | `qdrant.search` |
| `delete` | ~120 | `qdrant.delete` |
| `delete_silo_collection` | ~135 | `qdrant.delete_collection` |

### 2.2 engine/qdrant_store.py (11 methods)

| Method | Line | Operation Name |
|--------|------|----------------|
| `upsert` | ~85 | `qdrant_store.upsert` |
| `batch_upsert` | ~110 | `qdrant_store.batch_upsert` |
| `query` | ~145 | `qdrant_store.query` |
| `delete` | ~180 | `qdrant_store.delete` |
| `_ensure_collection` | ~200 | `qdrant_store.ensure_collection` |
| `delete_collection` | ~220 | `qdrant_store.delete_collection` |
| `get_cluster_info` | ~235 | `qdrant_store.cluster_info` |
| `list_collections` | ~250 | `qdrant_store.list_collections` |
| `get_collection_info` | ~265 | `qdrant_store.collection_info` |
| `count` | ~280 | `qdrant_store.count` |
| `scroll` | ~295 | `qdrant_store.scroll` |

### 2.3 stores/redis.py (14 methods)

| Method | Line | Operation Name |
|--------|------|----------------|
| `get` | ~40 | `redis.get` |
| `set` | ~55 | `redis.set` |
| `delete` | ~70 | `redis.delete` |
| `exists` | ~85 | `redis.exists` |
| `expire` | ~95 | `redis.expire` |
| `ttl` | ~105 | `redis.ttl` |
| `hget` | ~115 | `redis.hget` |
| `hset` | ~125 | `redis.hset` |
| `hdel` | ~135 | `redis.hdel` |
| `hgetall` | ~145 | `redis.hgetall` |
| `lpush` | ~155 | `redis.lpush` |
| `lrange` | ~165 | `redis.lrange` |
| `publish` | ~175 | `redis.publish` |
| `keys` | ~185 | `redis.keys` |

### 2.4 engine/postgres_store.py (6 methods)

| Method | Line | Operation Name |
|--------|------|----------------|
| `ensure_silo_config` | ~50 | `postgres.ensure_silo_config` |
| `upsert_chain_steps` | ~75 | `postgres.upsert_chain_steps` |
| `get_chain_steps` | ~100 | `postgres.get_chain_steps` |
| `delete_chain_steps` | ~125 | `postgres.delete_chain_steps` |
| `get_chain_steps_batch` | ~145 | `postgres.get_chain_steps_batch` |
| `add_orphaned_chain` | ~170 | `postgres.add_orphaned_chain` |

### 2.5 engine/memgraph_store.py (boundary methods only)

Add metrics to primary boundary methods (skip internal helpers):

| Method | Approx Line | Operation Name |
|--------|-------------|----------------|
| `execute_query` | ~120 | `memgraph.query` |
| `upsert_node` | ~200 | `memgraph.upsert_node` |
| `delete_node` | ~250 | `memgraph.delete_node` |
| `create_edge` | ~300 | `memgraph.create_edge` |
| `delete_edge` | ~350 | `memgraph.delete_edge` |
| `get_neighbors` | ~400 | `memgraph.get_neighbors` |
| `graph_search` | ~500 | `memgraph.graph_search` |
| `temporal_query` | ~600 | `memgraph.temporal_query` |

---

## Phase 3: LLM Token Export

### 3.1 Wire into LLMProvider._record_usage()

File: `src/context_service/llm/base.py`, method `_record_usage` (~line 70)

```python
def _record_usage(self, usage: Usage) -> None:
    """Accumulate token usage across calls for observability."""
    from context_service.telemetry.metrics import record_llm_tokens
    
    self._total_input_tokens += usage.input_tokens
    self._total_output_tokens += usage.output_tokens
    self._total_calls += 1
    
    record_llm_tokens(usage.model, usage.input_tokens, usage.output_tokens)
```

---

## Phase 4: Reasoning Chain Reuse Tracking

**Superseded by dedicated spec and plan.**

The naive hash-based approach below was found to produce false positives (chains sharing intermediate steps without being semantically substitutable). A proper design was developed:

- **Spec:** [`../specs/reasoning-chain-applicability.md`](../specs/reasoning-chain-applicability.md)
- **Plan:** [`2026-05-11-reasoning-chain-applicability.md`](./2026-05-11-reasoning-chain-applicability.md)

Key changes from original approach:
- Three-layer matching: query intent (embedding+ANN), step similarity (DTW), evidence accessibility
- "Applicability" not "equivalence" - can this chain answer the new query?
- Implicit feedback via session correlation for threshold tuning
- 11 implementation tasks, ~4-5 hours

Execute the dedicated plan instead of the steps below.

<details>
<summary>Original (deprecated) approach</summary>

### 4.1 Add hash lookup before chain creation

File: `src/context_service/mcp/tools/context_store.py`, function `_context_reason` (~line 410)

Before creating new chain, check for existing chain with same query_context_hash:

```python
# After resolving session_id, before chain creation:
from context_service.telemetry.metrics import record_reasoning_chain_reuse

query_context_hash = compute_query_hash(steps, evidence_used)  # Need to add this
existing = await store.find_chain_by_hash(silo_id, query_context_hash)
if existing:
    record_reasoning_chain_reuse(hit=True)
    return {"chain_id": existing.id, "reused": True}
record_reasoning_chain_reuse(hit=False)
```

### 4.2 Add find_chain_by_hash to memgraph_store

File: `src/context_service/engine/memgraph_store.py`

```python
async def find_chain_by_hash(self, silo_id: str, query_context_hash: str) -> dict | None:
    """Find existing reasoning chain by query context hash."""
    rows = await self.execute_query(
        queries.FIND_CHAIN_BY_HASH,  # Add to db/queries.py
        {"silo_id": silo_id, "query_context_hash": query_context_hash},
    )
    return rows[0] if rows else None
```

### 4.3 Add query to db/queries.py

```cypher
FIND_CHAIN_BY_HASH = """
MATCH (c:ReasoningChain {silo_id: $silo_id, query_context_hash: $query_context_hash})
WHERE c.status = 'active'
RETURN c.id AS id, c.created_at AS created_at
ORDER BY c.created_at DESC
LIMIT 1
"""
```

</details>

---

## Phase 5: Context Recall Response Sizing

### 5.1 Add response size tracking to context_recall

File: `src/context_service/mcp/tools/context_recall.py` (find main recall function)

After building response, before return:

```python
import json
from context_service.telemetry.metrics import record_context_recall_size

response_json = json.dumps(result)
response_bytes = len(response_json.encode('utf-8'))
estimated_tokens = response_bytes // 4  # rough heuristic

record_context_recall_size(
    layer=layer or "all",
    bytes_size=response_bytes,
    estimated_tokens=estimated_tokens,
)
```

---

## Execution Order

1. **Phase 1** - Metrics infrastructure (no functional changes, safe to merge first)
2. **Phase 2** - Database instrumentation (can be split into sub-PRs per store)
3. **Phase 3** - LLM token export (small, standalone)
4. **Phase 4** - Reasoning chain reuse (requires new query + store method)
5. **Phase 5** - Context recall sizing (small, standalone)

## Verification

After each phase:
1. Run `just check` (lint + typecheck)
2. Run `just test` to ensure no regressions
3. With OTEL enabled, verify metrics appear in SigNoz

## Estimated Effort

| Phase | Files | Estimated Time |
|-------|-------|----------------|
| 1 | 1 | 30 min |
| 2 | 5 | 2-3 hours |
| 3 | 1 | 15 min |
| 4 | 3 | 1 hour |
| 5 | 1 | 20 min |
| **Total** | **11** | **4-5 hours** |
