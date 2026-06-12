# MCP FusionRetriever Full Replacement Plan

## Context

The MCP `recall` tool currently uses `ContextService.query()` (single-channel semantic search). We've built a 4-channel `FusionRetriever` (semantic + BM25 + temporal + PPR with cross-encoder reranking) but it's not wired into MCP yet. REST `/api/v1/recall` is already wired.

**Goal:** Replace `ctx_svc.query()` with `FusionRetriever.retrieve()` in the MCP tool surface while preserving all existing features.

**Decision:** Full replacement (not hybrid) - cleaner long-term, avoids double-reranking.

## Current Architecture

```
recall (mcp/tools/recall.py)
  └─> _context_recall (mcp/tools/context_recall.py)
        └─> _context_query (mcp/tools/context_query.py:416)
              └─> ctx_svc.query()  <-- REPLACE THIS
              └─> _apply_reranking()
              └─> apply_epistemic_fusion()
```

## Features to Preserve

| Feature | Location | Action |
|---------|----------|--------|
| Result caching | `_get_result_cache()` | Keep - cache FusedResult list, bump cache version |
| Rerank caching | `_get_rerank_cache()` | **Remove** - FR handles reranking internally |
| Query expansion | `_maybe_expand_query()` | Keep - runs before FR |
| Epistemic fusion | `apply_epistemic_fusion()` | Keep - post-FR scoring adjustment |
| Layer TTL filtering | `_layer_ttls_map()` | **Keep in MCP layer** - post-FR filter (simpler) |
| Search mode | hybrid/dense/sparse | **Map to channel toggles** + deprecation warning |
| `include_superseded` | Filter param | Pass to FR channels |
| `filters` (QueryFilters) | Metadata filtering | Pass to FR channels |

### Search Mode Mapping

Map deprecated `search_mode` param to channel toggles:
- `dense` -> semantic only (disable BM25, temporal, PPR)
- `sparse` -> BM25 only (disable semantic, temporal, PPR)  
- `hybrid` (default) -> all channels enabled

Log deprecation warning when non-default value used. Remove param in next minor version.

## Changes

### Phase 1: Extend FusionRetriever

**File:** `src/context_service/retrieval/fusion.py`

1. Add `include_superseded: bool = False` param to `retrieve()`
2. Add `filters: QueryFilters | None = None` param to `retrieve()`
3. Pass these to all channel methods
4. Add `fetch_content: bool = False` for batch content fetch
5. Implement batch fetch via `graph_store.batch_get_nodes()`

New signature:
```python
async def retrieve(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    *,
    layers: list[str] | None = None,
    include_superseded: bool = False,
    filters: Any | None = None,
    fetch_content: bool = False,  # Batch fetch node content for enrichment
) -> list[FusedResult]:
```

Add to `FusedResult`:
```python
@dataclass
class FusedResult:
    node_id: str
    rrf_score: float
    channel_contributions: dict[str, float] = field(default_factory=dict)
    # Enriched fields (populated when fetch_content=True)
    content: str | None = None
    layer: str | None = None
    confidence: float | None = None
    conflict_status: str | None = None
    created_at: datetime | None = None
    tags: list[str] | None = None
```

**Batch fetch implementation** (at end of `retrieve()`):
```python
if fetch_content and fused:
    node_ids = [uuid.UUID(f.node_id) for f in fused[:top_k]]
    nodes_map = await self._ctx.graph_store.batch_get_nodes(node_ids, str(scope.silo_id))
    for f in fused:
        node = nodes_map.get(uuid.UUID(f.node_id))
        if node:
            f.content = node.content
            f.layer = node.properties.get("layer", node.type)
            f.confidence = node.properties.get("confidence", 0.0)
            f.conflict_status = node.properties.get("conflict_status", "none")
            f.created_at = node.created_at
            f.tags = list(node.properties.get("tags", []))
```

**Error handling:** FR already handles channel failures gracefully - each channel returns `ChannelResult(error=str(exc))` and fusion continues with remaining channels. No changes needed.

### Phase 2: Update context_query.py

**File:** `src/context_service/mcp/tools/context_query.py`

1. Import `FusionRetriever`

2. Add search_mode -> channel mapping helper:
```python
def _search_mode_to_channels(mode: str) -> dict[str, bool]:
    """Map deprecated search_mode to channel toggles."""
    if mode == "dense":
        logger.warning("search_mode='dense' deprecated, use channel config")
        return {"semantic": True, "bm25": False, "temporal": False, "ppr": False}
    if mode == "sparse":
        logger.warning("search_mode='sparse' deprecated, use channel config")
        return {"semantic": False, "bm25": True, "temporal": False, "ppr": False}
    return {"semantic": True, "bm25": True, "temporal": True, "ppr": True}
```

3. Replace `ctx_svc.query()` call (~line 416) with:
```python
channel_config = _search_mode_to_channels(search_mode)
retriever = FusionRetriever(ctx_svc, channel_config=channel_config)
fused_results = await retriever.retrieve(
    query=effective_query,
    scope=scope,
    top_k=top_k,
    layers=valid_layers,
    include_superseded=include_superseded,
    filters=parsed_filters,
    fetch_content=True,
)
```

4. Map `FusedResult` -> `QueryResult` for downstream compatibility:
```python
results = [
    QueryResult(
        node_id=uuid.UUID(f.node_id),
        layer=f.layer or "unknown",
        content=f.content or "",
        confidence=f.confidence or 0.0,
        relevance_score=f.rrf_score,
        conflict_status=f.conflict_status or "none",
        created_at=f.created_at,
        tags=f.tags,
    )
    for f in fused_results
]
```

5. **Remove** `_apply_reranking()` call - FR handles this internally
6. **Remove** `_get_rerank_cache()` usage - no longer needed
7. **Keep** `apply_epistemic_fusion()` - still needed for confidence/conflict scoring
8. **Keep** layer TTL filtering - apply post-FR as before

9. **Update result cache version** to invalidate stale entries:
```python
# In _get_result_cache() or cache key generation
CACHE_VERSION = "v2"  # Bump from v1
cache_key = f"{CACHE_VERSION}:{silo_id}:{query_hash}:..."
```

### Phase 3: Deprecate search_mode

The `search_mode` param (hybrid/dense/sparse) becomes obsolete since FR uses all channels. Options:

A. **Ignore silently** - FR always uses all channels
B. **Map to channel config** - `sparse` disables semantic, `dense` disables BM25
C. **Remove param** - Breaking change for API consumers

**Recommendation:** Option A for now, log deprecation warning.

### Phase 4: Update Tests

1. Update `tests/mcp/test_context_query.py` to expect FR behavior
2. Add integration test verifying 4-channel fusion via MCP
3. Verify epistemic fusion still applies correctly

## Migration Checklist

### Phase 1: Extend FusionRetriever
- [ ] Extend `FusedResult` dataclass with content fields
- [ ] Add `fetch_content` param to `FusionRetriever.retrieve()`
- [ ] Add `channel_config` param to `FusionRetriever.__init__()` for search_mode mapping
- [ ] Implement batch fetch via `graph_store.batch_get_nodes()` at end of retrieve()
- [ ] Add `include_superseded` and `filters` params, pass to channels

### Phase 2: Update context_query.py
- [ ] Import `FusionRetriever`
- [ ] Add `_search_mode_to_channels()` helper with deprecation warnings
- [ ] Replace `ctx_svc.query()` with `retriever.retrieve()`
- [ ] Map `FusedResult` -> `QueryResult` for compatibility
- [ ] Remove `_apply_reranking()` call
- [ ] Remove `_get_rerank_cache()` usage
- [ ] Keep `apply_epistemic_fusion()` post-processing
- [ ] Keep layer TTL filtering (post-FR)
- [ ] Bump cache version to invalidate stale entries

### Phase 3: Cleanup
- [ ] Remove unused rerank cache imports/code
- [ ] Update `.env.example` with channel toggle docs (already done)

### Phase 4: Tests
- [ ] Update `tests/mcp/test_context_query.py`
- [ ] Add integration test for 4-channel MCP recall
- [ ] Verify epistemic fusion still works
- [ ] Run `just ci`

## Risks

1. **Performance regression** - FR runs 4 channels vs 1. Mitigated by parallel execution. Monitor p95 latency.

2. **Memory pressure** - `fetch_content=True` pulls full node content for top_k results. For large top_k (50+) with verbose nodes, could increase memory. Mitigated by only fetching for final top_k, not fetch_k.

3. **Rerank cache removal** - Increases latency for repeated queries (cross-encoder runs every time). Acceptable tradeoff for simpler architecture. If problematic, add caching inside FR later.

4. **Cache invalidation** - Stale v1 cache entries during rollout. Mitigated by cache version bump. Old entries expire naturally (TTL).

5. **Channel failure cascade** - If Memgraph down, PPR channel fails. FR handles gracefully (returns partial results from other channels). No user-visible error unless ALL channels fail.

6. **search_mode behavior change** - Users expecting `sparse` to use SPLADE will now get BM25. Log deprecation warning. Document in changelog.

## Success Criteria

1. `just ci` passes
2. MCP recall returns results from all 4 channels
3. Epistemic fusion still adjusts scores by confidence/conflict
4. p95 latency < 500ms (allow slack for 4-channel overhead)
5. Existing MCP tests pass
