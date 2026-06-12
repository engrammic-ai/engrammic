# TEMPR Parity: Multi-Channel Retrieval + Benchmark

**Date:** 2026-06-12
**Status:** Draft
**Timeline:** 3 days (parallel agent development)
**Branch:** `feat/read-path-epistemic-fusion` (extends existing work)

## Context

Research into Hindsight (vectorize-io) integration revealed architectural incompatibility with CITE schema. However, their TEMPR retrieval pipeline (4-channel parallel retrieval + RRF + reranker) is a proven pattern we can implement on our own substrate.

**Decision:** Path A (own substrate) confirmed. Borrow TEMPR patterns, don't depend on Hindsight.

**Goal:** Full TEMPR parity (all 4 channels + reranker) then run mem0 benchmark on epistemic slices. All-or-nothing scope.

## Architecture

### Current State

```
Query -> Semantic (Qdrant) -> Graph (BFS) -> RRF Fusion -> Epistemic Fusion -> Results
```

### Target State

```
Query --+-> Semantic (Qdrant)      -+
        +-> BM25 (Postgres GIN)    -+-> RRF Fusion -> Reranker -> Epistemic Fusion -> Results
        +-> Temporal (date parse)  -+
        +-> Graph (PPR from seeds) -+
```

### Design Decisions

1. **Channels are independent** - each returns `ChannelResult` (ranked node IDs + latency). No inter-channel dependencies except Graph seeds from Semantic hits.

2. **RRF fusion (k=60)** - same as Hindsight. Proven, no tuning needed.

3. **Reranker post-RRF** - cross-encoder scores fused candidates, not per-channel. Model: `cross-encoder/ms-marco-MiniLM-L-6-v2`.

4. **Epistemic fusion last** - existing step 1 code (`rerank * ((1-w) + w*confidence)`) operates on reranker output.

5. **Feature-flagged channels** - each channel has `enabled: bool` in config.

## Channel Specifications

### BM25 Channel

**Purpose:** Keyword/full-text search for exact-match queries semantic embeddings miss.

**Implementation:**
- Alembic migration: GIN index on `nodes.content`
- Method: `_bm25_channel()` in `FusionRetriever`
- Scoring: `ts_rank` with `plainto_tsquery`
- Returns: top-k node IDs ranked by BM25 score

**Config:**
```python
class BM25ChannelConfig(BaseModel):
    enabled: bool = True
    top_k: int = 100
```

### Temporal Channel

**Purpose:** Date-aware retrieval for "what did I learn last week" queries.

**Implementation:**
- Date parser: `dateutil` for relative dates ("last week", "since Monday")
- If dates detected: filter by `created_at` range, weight by proximity
- If no dates: weight by recency with half-life decay
- Returns: top-k node IDs ranked by temporal relevance

**Config:**
```python
class TemporalChannelConfig(BaseModel):
    enabled: bool = True
    memory_half_life_days: int = 14
    knowledge_half_life_days: int = 90
```

### PPR Graph Channel

**Purpose:** Replace BFS with Personalized PageRank for principled relevance decay.

**Implementation:**
- Seed: top-k semantic hits
- Algorithm: PPR with damping 0.85
- Edge weights: `SYNTHESIZED_FROM` and `SUPERSEDES` weighted higher than `LINK`
- Reference: HippoRAG 2 `run_ppr` (MIT licensed)
- Returns: top-k node IDs ranked by PPR score

**Config:**
```python
class GraphChannelConfig(BaseModel):
    enabled: bool = True
    damping: float = 0.85
    max_iterations: int = 50
    edge_weights: dict[str, float] = {
        "SYNTHESIZED_FROM": 1.5,
        "SUPERSEDES": 1.5,
        "LINK": 1.0,
    }
```

### Reranker

**Purpose:** Cross-encoder reranking for query-document relevance that bi-encoders miss.

**Implementation:**
- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (same as Hindsight)
- Input: top-k RRF results (default 50)
- Output: `rerank_score` per result
- Fallback: if model fails, use RRF scores directly

**Config:**
```python
class RerankerConfig(BaseModel):
    enabled: bool = True
    model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    top_k: int = 50
```

## Integration

### Pipeline Flow

```python
async def retrieve(query: str, scope: ScopeContext, top_k: int) -> list[FusedResult]:
    # 1. Run channels in parallel
    semantic, bm25, temporal = await asyncio.gather(
        self._semantic_channel(query, scope, top_k=100),
        self._bm25_channel(query, scope, top_k=100),
        self._temporal_channel(query, scope, top_k=100),
    )
    
    # 2. Graph channel seeds from semantic (sequential)
    graph = await self._ppr_channel(semantic.ranked_ids[:20], scope, top_k=100)
    
    # 3. RRF fusion
    fused = self._rrf_fuse([semantic, bm25, temporal, graph], k=60)
    
    # 4. Rerank
    reranked = await self._rerank(query, fused[:50])
    
    # 5. Epistemic fusion (existing)
    final = apply_epistemic_fusion(reranked, settings.epistemic_fusion)
    
    return final[:top_k]
```

### File Changes

| File | Change |
|------|--------|
| `retrieval/fusion.py` | Add `_bm25_channel`, `_temporal_channel`, `_ppr_channel`, `_rerank` |
| `retrieval/reranker.py` | New - cross-encoder wrapper |
| `retrieval/temporal.py` | New - date parsing + decay |
| `engine/memgraph_store.py` | Add PPR query |
| `config/settings.py` | Add channel configs |
| `alembic/versions/xxx_add_gin_index.py` | BM25 migration |

### Fallback Behavior

- Disabled/errored channel returns empty `ChannelResult`
- RRF handles missing channels gracefully
- Reranker failure falls back to RRF scores

### Observability

- Channel latencies logged via structlog
- `FusedResult.channel_contributions` extended for new channels
- OTEL spans for reranker

## Benchmark

### Scope

mem0 head-to-head on epistemic slices only. Harness exists at `../longmemeval-harness`.

### Epistemic Slices

| Slice | Tests |
|-------|-------|
| `supersession` | Returns current belief, not superseded |
| `contradiction` | Conflicts flagged/demoted, not confidently wrong |
| `abstention` | Low-confidence triggers "I don't know" |

### Metrics

- **Accuracy** - % correct per judge
- **Tokens retrieved** - context size
- **Tokens per correct** - efficiency metric
- **Latency p50/p95**

### Adapters

- `engrammic.py` - calls our MCP recall
- `mem0.py` - calls mem0 API

## Schedule

### Day 1: BM25 + Temporal (parallel worktrees)

**Worktree 1 (BM25):**
- Alembic migration for GIN index
- `_bm25_channel()` method
- BM25ChannelConfig
- Unit tests

**Worktree 2 (Temporal):**
- Date parser module
- `_temporal_channel()` method
- TemporalChannelConfig
- Unit tests

**EOD:** Merge both to main branch

### Day 2: Reranker + PPR (parallel worktrees)

**Worktree 1 (Reranker):**
- `retrieval/reranker.py`
- Cross-encoder integration
- RerankerConfig
- Unit + fallback tests

**Worktree 2 (PPR):**
- PPR query in memgraph_store
- `_ppr_channel()` method
- GraphChannelConfig
- Unit tests

**EOD:** Merge both, run integration tests

### Day 3: Integration + Benchmark

**Morning:**
- Integration testing
- Fix edge cases
- Opus 4.8 review

**Afternoon:**
- Add epistemic slice cases to harness
- Run benchmark vs mem0
- Generate report

## Kill Criteria

- Day 2 merge >2hr conflicts: simplify PPR to enhanced BFS
- Benchmark harness >4hr: skip tokens metric, accuracy only
- mem0 adapter blocked: run Engrammic-only baseline

## Testing Strategy

| Component | Type | Coverage |
|-----------|------|----------|
| BM25 | Unit | GIN query, ranking |
| Temporal | Unit | Date parsing, decay math |
| PPR | Unit | Seed propagation, damping |
| Reranker | Unit | Model loading, fallback |
| Pipeline | Integration | Full flow with mock store |
| E2E | E2E | Real stores, sample queries |

TDD approach: failing test first, then implementation.

## Dependencies

- `sentence-transformers` (reranker model)
- `python-dateutil` (temporal parsing)
- Existing: Qdrant, Memgraph, Postgres, FastEmbed

## Success Criteria

1. All 4 channels operational and feature-flagged
2. Reranker integrated with fallback
3. `just check` passes (mypy strict + ruff)
4. Integration tests green
5. Benchmark shows Engrammic wins epistemic slices vs mem0
