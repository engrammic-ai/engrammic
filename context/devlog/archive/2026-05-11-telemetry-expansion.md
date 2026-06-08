# Devlog: Telemetry Expansion

**Date:** 2026-05-11
**Branch:** `main`
**Status:** Complete

## Summary

Expanded OTEL instrumentation to cover all storage backends, LLM token tracking, and context_recall response sizing. Deployed to strata-finance and verified metrics appearing in SigNoz.

## Changes

### New metrics instruments

Added to `src/context_service/telemetry/metrics.py`:

- `llm.tokens` (Counter) - input/output tokens by model
- `context.recall.size` (Histogram) - estimated response size by layer

### LLM token export

Wired `record_llm_tokens()` into `LLMProvider._record_usage()` in `llm/base.py`. Every LLM call now emits token counts to OTEL with model attribution.

### Context recall sizing

Added heuristic size estimation to `mcp/tools/context_recall.py`:

```python
node_count = len(result.get("results", result.get("nodes", [])))
avg_node_bytes = 500 if include_content else 100
estimated_bytes = node_count * avg_node_bytes + 200
```

Avoided `json.dumps()` in hot path to prevent double serialization. Initial approach with `estimated_tokens` attribute caused cardinality explosion (continuous values create unbounded time series) - removed it.

### Database instrumentation

Added `record_db_query(operation, duration_ms)` calls to all uninstrumented store methods:

| Store | Methods instrumented |
|-------|---------------------|
| `stores/qdrant.py` | 6 |
| `engine/qdrant_store.py` | 11 |
| `stores/redis.py` | 14 |
| `engine/postgres_store.py` | 6 |

Memgraph was already instrumented.

## Deployment

Deployed to strata-finance via `git pull && docker compose build --no-cache && docker compose up -d --force-recreate`.

Verified in SigNoz:
- `context.recall.size` histogram populating on MCP calls
- `db.query.duration` showing `qdrant.*`, `redis.*` operations
- `llm.tokens` pending (requires Custodian synthesis run)

## Dagster debugging

Manual Custodian runs were failing silently after resource init. Investigation revealed:

1. All 14 schedules and 10 sensors were STOPPED
2. `heat` asset requires partition selection (dynamic partitions by silo_id)
3. `belief_synthesis` asset requires `cluster_id` run tag from its sensor

Fixes:
- `dagster schedule start --start-all` 
- `dagster sensor start --start-all`
- Manual `heat` run with partition succeeded

## Deferred

**Reasoning chain reuse tracking** - requires solving chain equivalence problem first. Structural hashing (steps/evidence) causes false positives (chains about different topics can share intermediate steps). Options to explore: intent+outcome hashing, query_intent field, semantic similarity. Logged to memory.

## Metrics available

| Metric | Dimensions |
|--------|------------|
| `llm.tokens` | model, type (input/output) |
| `context.recall.size` | layer |
| `db.query.duration` | db.operation |
| `mcp.tool.duration` | mcp.tool, success |
| `mcp.tool.invocations` | mcp.tool, success |
