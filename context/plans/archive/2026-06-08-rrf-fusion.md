# Cross-Channel RRF Fusion for Recall

**Branch:** `feat/rrf-fusion`
**Status:** Ready

## Goal

Fuse vector and graph retrieval channels via RRF instead of mode-switching. Current recall throws away signal by dispatching to either vector (`depth=0`) or graph (`depth>0`), never both.

**Inspired by:** Hindsight/TEMPR 4-way fusion (see `context/competitive/hindsight-tempr.md`)

**Opus advisor assessment:**
- Cross-channel RRF: 8-12% lift on recall@5, ~50 lines core. DO IT.
- Temporal NLU auto-detection: 1-2% net lift, high complexity. SKIP.
- Explicit `since`/`until` params: ~2 hours, simple. DO THIS INSTEAD.
- BM25: SPLADE already covers lexical. SKIP.

## Scope

1. **Cross-channel RRF fusion** — Run semantic + graph in parallel, fuse with RRF
2. **Explicit temporal params** — Add `since`/`until` to recall API (no NLU parsing)

## Architecture

```
┌─────────────────────────────────────────────────┐
│         _context_recall (Orchestrator)          │
│                                                 │
│  fusion_mode=True ──────────────────────────────┤
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│            FusionRetriever                      │
│   (src/context_service/retrieval/fusion.py)     │
└─────────────────────┬───────────────────────────┘
                      │
       ┌──────────────┴──────────────┐
       ▼                             ▼
┌─────────────┐               ┌─────────────┐
│  Semantic   │               │    Graph    │
│  Channel    │               │   Channel   │
│ (Qdrant)    │               │ (Memgraph)  │
└──────┬──────┘               └──────┬──────┘
       │                             │
       └──────────────┬──────────────┘
                      ▼
           ┌──────────────────┐
           │    RRF Fusion    │
           │ score = Σ 1/(k+r)│
           └────────┬─────────┘
                    ▼
           ┌──────────────────┐
           │ Temporal Filter  │  ← simple: filter by since/until if provided
           └────────┬─────────┘
                    ▼
           ┌──────────────────┐
           │ LiteLLM Reranker │  ← existing, unchanged
           └──────────────────┘
```

## Tasks

### Phase 1: Core fusion module

- [ ] Create `src/context_service/retrieval/__init__.py`
- [ ] Create `src/context_service/retrieval/fusion.py`:
  - `ChannelResult` dataclass (channel_name, ranked_ids, latency_ms, error)
  - `FusedResult` dataclass (node_id, rrf_score, channel_contributions)
  - `FusionRetriever` class with `retrieve()` and `_fuse_rrf()` methods
  - Semantic channel wrapper (calls `ctx_svc.query()`)
  - Graph channel wrapper (calls `ctx_svc.graph_traversal()`)
- [ ] Add `FusionConfig` to `src/context_service/config/settings.py`:
  - `enabled: bool = False`
  - `rrf_k: int = 60`
  - `default_graph_depth: int = 2`

### Phase 2: Temporal filter (explicit params only)

- [ ] Add `_parse_relative_time()` helper: parses "7d", "1w", "30d", ISO datetime
- [ ] Add `_filter_temporal()`: batch-fetches valid_from, filters by since/until window
- [ ] No NLU parsing — explicit params only

### Phase 3: Wire to MCP

- [ ] Modify `src/context_service/mcp/tools/context_recall.py`:
  - Add `fusion_mode: bool = False` param
  - Add `since: str | None = None` param
  - Add `until: str | None = None` param
  - Dispatch to `FusionRetriever` when `fusion_mode=True and query`
  - Apply temporal filter post-fusion if since/until provided
- [ ] Update `src/context_service/mcp/config/mcp_tools.yaml`:
  - Add new params to `recall` tool schema
  - Add `fusion_meta` to response description

### Phase 4: Tests

- [ ] `test_rrf_fusion` — verify fusion math with mock channel results
- [ ] `test_temporal_filter` — verify since/until filtering
- [ ] `test_fusion_graceful_degradation` — one channel fails, other still returns
- [ ] Integration test with real stores

## Files changed

| File | Change |
|------|--------|
| `src/context_service/retrieval/__init__.py` | NEW: module init |
| `src/context_service/retrieval/fusion.py` | NEW: FusionRetriever, ChannelResult, FusedResult |
| `src/context_service/mcp/tools/context_recall.py` | Add fusion_mode, since, until params |
| `src/context_service/config/settings.py` | Add FusionConfig |
| `src/context_service/mcp/config/mcp_tools.yaml` | Add new params to recall tool |

## Out of scope

- BM25 channel (SPLADE sufficient)
- Temporal NLU auto-detection (explicit params only)
- Spreading activation with decay (BFS sufficient)
- Cross-encoder post-fusion (keep existing reranker)
- Channel weights (all channels weighted equally for now)

## Done criteria

- [ ] `just check` passes
- [ ] `just test -k fusion` passes
- [ ] Manual test: `recall(query="...", fusion_mode=True)` returns fused results
- [ ] Manual test: `recall(query="...", fusion_mode=True, since="7d")` filters by time
- [ ] Performance: fusion recall < 250ms (parallel execution)

## Performance targets

- Semantic channel: ~50-80ms (Qdrant + embedding)
- Graph channel: ~80-150ms (Qdrant seed + BFS)
- Fusion overhead: ~10ms
- Total (parallel): ~100-150ms pre-rerank
- End-to-end target: <250ms
