# Devlog: 2026-05-12 - Full QA Pass & Bug Fixes

## Summary

Ran comprehensive QA testing across 9 scenarios covering the full EAG stack. Discovered 3 bugs, fixed them same-day, verified fixes in production.

## QA Scenarios Executed

| ID | Scenario | Status |
|----|----------|--------|
| 001 | Multi-agent memory sharing | Pass (3 Sonnet workers) |
| 005 | Metacognition reflections | Pass |
| 006 | Wisdom & memory research | Pass |
| 007 | Contradiction detection | Pass |
| 008 | Provenance chains | Pass |
| 009 | Temporal queries | Found BUG-001 |
| 010 | Link semantics | Pass (7 relationship types) |
| 011 | Search quality | Pass |
| 012 | Reasoning chains | Found BUG-003 |

## Bugs Found & Fixed

### BUG-001: Time-travel `as_of` returned node_not_found

**Symptom:** Querying superseded node at timestamp before supersession returned `node_not_found` instead of the valid historical state.

**Root cause:** Nodes created via `context.store()` lacked `committed = true` property. The temporal query `GET_NODES_BY_IDS_TEMPORAL` filters by `WHERE n.committed = true`, so these nodes were invisible.

**Fix:** Added `committed: true` to CREATE query in `context.py:228`

### BUG-002: MetaObservation polluted memory searches

**Symptom:** Meta observations showed up in memory layer searches because they defaulted to `layer="memory"`.

**Root cause:** `reflect()` method didn't set `layer` property on MetaObservation nodes.

**Fix:** Added `props["layer"] = "meta"` in `reflect()` method.

### BUG-003: ReasoningChain invisible to retrieval

**Symptom:** Intelligence layer nodes returned `node_not_found` when querying by chain_id with `include_steps=true`.

**Root cause:** `upsert_reasoning_chain()` created nodes with `:ReasoningChain` label only. Generic retrieval queries `MATCH (n:Node ...)` so these nodes were invisible.

**Fix:** Changed to `:ReasoningChain:Node` dual label, added `layer`, `type`, `committed` properties.

## Latency Analysis

Validated that observed latencies are expected:
- Jina embedding: ~500ms
- Network to strata-finance: ~100ms  
- Embeddings are async with Redis caching (cache hits skip Jina)

Search queries hitting cached embeddings explain sub-300ms responses despite Jina overhead.

## Multi-Agent Test

Successfully ran scenario 001 with 3 parallel Sonnet agents:
- Each stored 3 observations on assigned topic
- Cross-agent discovery via semantic search worked
- Created 3 cross-worker RELATED_TO links
- Total execution: ~45 seconds

## Commit

```
0661189 fix: resolve QA-discovered bugs in temporal queries, meta layer, and intelligence layer
```

## Files Changed

- `src/context_service/services/context.py` - Added `committed: true` to store(), `layer: "meta"` to reflect()
- `src/context_service/engine/memgraph_store.py` - Changed ReasoningChain to dual `:ReasoningChain:Node` label

## Verification

All fixes verified on strata-finance:
- BUG-001: `as_of` query returns superseded node correctly
- BUG-002: MetaObservation shows `layer: "meta"`  
- BUG-003: ReasoningChain retrievable by ID with steps
