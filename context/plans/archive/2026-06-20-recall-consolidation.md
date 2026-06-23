# Recall Pipeline Consolidation

**Date:** 2026-06-20
**Status:** Spec
**Goal:** Unify FusionRetriever (4-channel retrieval) with sage/recall.py (epistemic features)

## Problem

Two parallel recall implementations exist:

| Component | Retrieval | Epistemic Features |
|-----------|-----------|-------------------|
| FusionRetriever | 4-channel (semantic, BM25, temporal, PPR) + RRF + rerank | None |
| sage/recall.py | Single-channel vector search | as_of, lazy synthesis, hints, layer scoring |

FusionRetriever is production but lacks epistemic features. sage/recall.py has the features but inferior retrieval. Neither calls the other.

## Target Architecture

```
recall.py
  │
  ├─→ FusionRetriever.retrieve()          # 4-channel retrieval (KEEP)
  │     └─→ RRF fusion + rerank
  │
  └─→ apply_epistemic_pipeline()          # NEW: extracted from sage/recall.py
        ├─→ apply_as_of_filter()          # Temporal filtering
        ├─→ apply_layer_scoring()         # Layer-specific score adjustments
        ├─→ maybe_trigger_synthesis()     # Fire-and-forget lazy synthesis
        └─→ detect_hints()                # Belief candidates, chain continuations
```

## What to Extract from sage/recall.py

### Keep (move to `retrieval/epistemic.py`)

| Function/Class | Lines | Purpose |
|----------------|-------|---------|
| `RecallOptions` | 47-57 | Query options dataclass |
| `RecallHint` | 113-119 | Hint dataclass |
| `RecallResponse` | 123-136 | Extended response with hints |
| `_detect_belief_candidates()` | 138-181 | Hint detection |
| `_detect_chain_continuations()` | 184-262 | Hint detection |
| `compute_recall_score()` | 279-325 | Layer-specific scoring |
| as_of filtering logic | 476-490 | Temporal filter |
| lazy synthesis logic | 575-620 | Synthesis trigger |

### Discard (replaced by FusionRetriever)

| Function | Lines | Reason |
|----------|-------|--------|
| Vector search | 441-447 | FusionRetriever does 4-channel |
| PPR scoring | 512-524 | FusionRetriever has PPR channel |
| `_get_ppr_scores()` | 328-404 | Duplicate of retrieval/ppr.py |
| `traverse_graph()` | (if exists) | context_query.py handles depth |

### Keep in place (reuse as imports)

| Item | Purpose |
|------|---------|
| `Layer` enum | Already duplicated in models/mcp.py, consolidate |
| `ConfidenceBreakdown` | Useful for transparency |
| `RecallResultItem` | May adapt to FusionRetriever output |
| Scoring constants | `MEMORY_DECAY_SIGMA`, etc. |

## New Module: `retrieval/epistemic.py`

```python
"""Epistemic post-processing hooks for recall pipeline.

Extracted from sage/recall.py to work with FusionRetriever output.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings
from context_service.models.mcp import Layer  # Canonical Layer enum
from context_service.retrieval.fusion import FusedResult
from context_service.signals.freshness import compute_freshness

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)


@dataclass
class EpistemicOptions:
    """Options for epistemic post-processing."""
    as_of: datetime | None = None
    include_synthesis: bool = True
    include_hints: bool = False
    min_confidence: float = 0.0


@dataclass 
class RecallHint:
    """Hint suggesting an action based on recall results."""
    hint_type: str  # "belief_candidate" | "chain_continuation"
    message: str
    node_ids: list[str] = field(default_factory=list)
    suggested_action: str | None = None


@dataclass
class EpistemicResult:
    """Result of epistemic post-processing."""
    results: list[FusedResult]
    hints: list[RecallHint] = field(default_factory=list)
    synthesis_pending: bool = False


async def apply_epistemic_pipeline(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    options: EpistemicOptions | None = None,
    llm: Any | None = None,
    query_embedding: list[float] | None = None,
) -> EpistemicResult:
    """Apply epistemic post-processing to FusionRetriever results.
    
    Pipeline:
    1. as_of temporal filter (if options.as_of set)
    2. Confidence filter (if options.min_confidence > 0)
    3. Layer-specific score adjustment
    4. Lazy synthesis trigger (fire-and-forget)
    5. Hint detection (if options.include_hints)
    """
    if options is None:
        options = EpistemicOptions()
    
    # 1. as_of filter
    if options.as_of:
        results = apply_as_of_filter(results, options.as_of)
    
    # 2. Confidence filter
    if options.min_confidence > 0:
        results = [r for r in results if (r.confidence or 0) >= options.min_confidence]
    
    # 3. Layer scoring adjustment
    results = apply_layer_scoring(results)
    
    # 4. Lazy synthesis (fire-and-forget)
    synthesis_pending = False
    if options.include_synthesis and llm is not None:
        synthesis_pending = await maybe_trigger_synthesis(
            results, silo_id, store, llm
        )
    
    # 5. Hints
    hints: list[RecallHint] = []
    if options.include_hints:
        hints = await detect_hints(results, silo_id, store, query_embedding)
    
    return EpistemicResult(
        results=results,
        hints=hints,
        synthesis_pending=synthesis_pending,
    )


def apply_as_of_filter(
    results: list[FusedResult],
    as_of: datetime,
) -> list[FusedResult]:
    """Filter results to state valid at as_of time.
    
    Keeps nodes where:
    - created_at <= as_of
    - valid_to is None OR valid_to > as_of
    """
    filtered = []
    for r in results:
        # Skip if created after as_of
        if r.created_at and r.created_at > as_of:
            continue
        
        # Skip if superseded before as_of (valid_to in properties)
        valid_to = r.properties.get("valid_to") if r.properties else None
        if valid_to:
            if isinstance(valid_to, str):
                valid_to = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
            if valid_to <= as_of:
                continue
        
        filtered.append(r)
    
    return filtered


def apply_layer_scoring(results: list[FusedResult]) -> list[FusedResult]:
    """Adjust RRF scores based on layer semantics.
    
    - Memory: freshness decay
    - Knowledge: corroboration boost  
    - Wisdom: staleness penalty
    - Intelligence: no adjustment
    
    Modifies rrf_score in place and re-sorts.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    
    for r in results:
        if not r.layer:
            continue
            
        layer = r.layer.upper()
        
        if layer == Layer.MEMORY.value:
            # Freshness decay
            if r.created_at:
                freshness = compute_freshness(
                    r.created_at, now, 
                    sigma_days=settings.memory_decay_sigma
                )
                weight = settings.freshness_weight
                r.rrf_score = r.rrf_score * ((1.0 - weight) + weight * freshness)
                
        elif layer == Layer.KNOWLEDGE.value:
            # Corroboration boost
            corroboration = r.properties.get("corroboration_count", 0) if r.properties else 0
            if corroboration > 0:
                boost = math.log10(1 + corroboration) * 0.2
                r.rrf_score = r.rrf_score * (1 + boost)
                
        elif layer == Layer.WISDOM.value:
            # Staleness penalty
            synthesis_state = r.properties.get("synthesis_state") if r.properties else None
            if synthesis_state == "STALE":
                r.rrf_score = r.rrf_score * 0.5
    
    # Re-sort by adjusted score
    results.sort(key=lambda x: x.rrf_score, reverse=True)
    return results


async def maybe_trigger_synthesis(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    llm: Any,
) -> bool:
    """Fire-and-forget synthesis for ready clusters.
    
    Returns True if any synthesis was triggered (synthesis_pending).
    Does NOT block on synthesis completion.
    """
    from context_service.db import queries as q
    from context_service.sage.transactions import synthesize
    
    node_ids = [r.node_id for r in results]
    if not node_ids:
        return False
    
    cluster_results = await store.execute_query(
        q.GET_CLUSTERS_FOR_NODES,
        {"silo_id": silo_id, "node_ids": node_ids},
    )
    
    synthesis_pending = False
    
    for cluster in cluster_results:
        cluster_id = cluster.get("cluster_id")
        if not cluster_id:
            continue
            
        cluster_state = cluster.get("state")
        current_belief_id = cluster.get("current_belief_id")
        
        # Only trigger for READY/STALE clusters without beliefs
        if cluster_state not in ("READY", "STALE") or current_belief_id:
            continue
        
        # Backoff: skip if too many attempts
        attempts = cluster.get("synthesis_attempts", 0)
        if attempts >= 3:
            continue
        
        # Fire-and-forget
        asyncio.create_task(
            _run_synthesis_with_backoff(store, cluster_id, silo_id, llm)
        )
        synthesis_pending = True
    
    return synthesis_pending


async def _run_synthesis_with_backoff(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: Any,
) -> None:
    """Background synthesis with attempt tracking."""
    from context_service.sage.transactions import synthesize
    
    try:
        # Increment attempt counter
        await store.execute_query(
            "MATCH (c:Cluster {id: $id}) SET c.synthesis_attempts = coalesce(c.synthesis_attempts, 0) + 1",
            {"id": cluster_id},
        )
        await synthesize(store, cluster_id, silo_id, llm)
        # Reset counter on success
        await store.execute_query(
            "MATCH (c:Cluster {id: $id}) SET c.synthesis_attempts = 0",
            {"id": cluster_id},
        )
    except Exception as e:
        logger.warning("lazy_synthesis_failed", cluster_id=cluster_id, error=str(e))


async def detect_hints(
    results: list[FusedResult],
    silo_id: str,
    store: HyperGraphStore,
    query_embedding: list[float] | None,
) -> list[RecallHint]:
    """Detect belief candidates and chain continuations."""
    hints: list[RecallHint] = []
    
    # Belief candidates
    hints.extend(await _detect_belief_candidates(store, results, silo_id))
    
    # Chain continuations
    if query_embedding:
        hints.extend(await _detect_chain_continuations(query_embedding, silo_id))
    
    return hints


async def _detect_belief_candidates(
    store: HyperGraphStore,
    results: list[FusedResult],
    silo_id: str,
) -> list[RecallHint]:
    """Detect when facts cluster enough to suggest belief formation."""
    from context_service.db import queries as q
    
    hints: list[RecallHint] = []
    
    # Need 3+ knowledge-layer results
    knowledge_ids = [
        r.node_id for r in results 
        if r.layer and r.layer.upper() == Layer.KNOWLEDGE.value
    ]
    if len(knowledge_ids) < 3:
        return hints
    
    cluster_result = await store.execute_query(
        q.GET_CLUSTERS_FOR_NODES_WITH_FACTS,
        {"silo_id": silo_id, "node_ids": knowledge_ids},
    )
    
    for cluster in cluster_result:
        fact_count = cluster.get("fact_count", 0)
        has_belief = cluster.get("current_belief_id") is not None
        cluster_state = cluster.get("state")
        
        # Skip if already queued for synthesis
        if cluster_state in ("READY", "STALE"):
            continue
        
        if fact_count >= 3 and not has_belief:
            fact_ids = (cluster.get("fact_ids") or [])[:5]
            hints.append(RecallHint(
                hint_type="belief_candidate",
                message=f"{fact_count} corroborating facts found. Consider forming a belief.",
                node_ids=fact_ids,
                suggested_action=f"decide(decision='...', about={fact_ids[:3]})",
            ))
    
    return hints


async def _detect_chain_continuations(
    query_embedding: list[float],
    silo_id: str,
) -> list[RecallHint]:
    """Find reasoning chains whose conclusions are relevant to this query."""
    # Extracted from sage/recall.py:184-262
    # Searches reasoning_chains collection in Qdrant
    # Returns hints when prior chains have relevant conclusions
    
    # Import inline to avoid circular deps
    import asyncio
    from qdrant_client.http import models as qdrant_models
    from context_service.mcp.server import get_context_service
    
    if not query_embedding:
        return []
    
    try:
        ctx_svc = get_context_service()
        client = await ctx_svc._qdrant._get_client()
    except Exception:
        return []
    
    try:
        collections = await asyncio.wait_for(client.get_collections(), timeout=0.5)
        if "reasoning_chains" not in {c.name for c in collections.collections}:
            return []
    except Exception:
        return []
    
    try:
        response = await asyncio.wait_for(
            client.query_points(
                collection_name="reasoning_chains",
                query=query_embedding,
                query_filter=qdrant_models.Filter(
                    must=[qdrant_models.FieldCondition(
                        key="silo_id",
                        match=qdrant_models.MatchValue(value=silo_id),
                    )]
                ),
                limit=3,
                score_threshold=0.7,
            ),
            timeout=1.0,
        )
    except Exception:
        return []
    
    hints: list[RecallHint] = []
    for point in response.points:
        payload = point.payload or {}
        chain_id = payload.get("chain_id") or payload.get("node_id") or str(point.id)
        conclusion = (payload.get("conclusion") or "")[:100]
        
        hints.append(RecallHint(
            hint_type="chain_continuation",
            message=f'Prior reasoning: "{conclusion}..."',
            node_ids=[chain_id],
            suggested_action=f"reason(steps=[...], parent_chain_id='{chain_id}')",
        ))
    
    return hints
```

## Integration Point: context_query.py

Current flow:
```python
# context_query.py
async def _context_query(...):
    results = await fusion_retriever.retrieve(query, ...)
    results = apply_epistemic_fusion(results, ...)  # confidence/conflict
    return results
```

New flow:
```python
# context_query.py
from context_service.retrieval.epistemic import (
    apply_epistemic_pipeline,
    EpistemicOptions,
)

async def _context_query(..., as_of=None, include_hints=False):
    # 1. Retrieval (unchanged)
    results = await fusion_retriever.retrieve(query, ...)
    results = apply_epistemic_fusion(results, ...)
    
    # 2. Epistemic post-processing (NEW)
    epistemic_opts = EpistemicOptions(
        as_of=as_of,
        include_hints=include_hints,
        include_synthesis=True,
    )
    epistemic_result = await apply_epistemic_pipeline(
        results, silo_id, store, epistemic_opts, llm, query_embedding
    )
    
    return epistemic_result
```

## MCP Tool Changes

Add `as_of` and `include_hints` params to recall tool:

```yaml
# mcp_tools.yaml
recall:
  params:
    query: ...
    as_of:
      type: string
      description: "ISO datetime or relative ('7d ago'). Query historical state."
    include_hints:
      type: boolean
      default: false
      description: "Include belief candidate and chain continuation hints."
```

## Migration Steps

### Step 0: Add scoring constants to settings.py (15m)

```python
# config/settings.py - add to Settings class
memory_decay_sigma: float = Field(default=90.0, description="Days for memory decay half-life")
max_graph_depth: int = Field(default=3, description="Max depth for graph traversal")
```

### Step 1: Extend FusedResult (10m)

```python
# retrieval/fusion.py - add to FusedResult dataclass
properties: dict[str, Any] = field(default_factory=dict)
```

Update `_fetch_node_content()` to populate `properties` with `valid_to`, `corroboration_count`, `synthesis_state`.

### Step 2: Create `retrieval/epistemic.py` (2h)

- Copy the module spec above
- Import `Layer` from `models/mcp.py`
- Import `FusedResult` from `retrieval/fusion.py`

### Step 3: Wire into context_query.py (1h)

```python
from context_service.retrieval.epistemic import (
    apply_epistemic_pipeline,
    EpistemicOptions,
    EpistemicResult,
)

async def _context_query(..., as_of=None, include_hints=False) -> EpistemicResult:
    # Existing retrieval
    results = await fusion_retriever.retrieve(query, ...)
    results = apply_epistemic_fusion(results, ...)
    
    # NEW: epistemic post-processing
    return await apply_epistemic_pipeline(
        results, silo_id, store,
        options=EpistemicOptions(as_of=as_of, include_hints=include_hints),
        llm=llm,
        query_embedding=query_embedding,
    )
```

### Step 4: Update MCP tool (30m)

```yaml
# mcp_tools.yaml - recall params
as_of:
  type: string
  description: "ISO datetime or relative ('7d ago', 'last tuesday')"
include_hints:
  type: boolean
  default: false
```

Add date parsing in `recall.py`:
```python
from context_service.retrieval.temporal import parse_temporal_reference

if as_of:
    as_of_dt = parse_temporal_reference(as_of)  # Already exists
```

### Step 5: Test (2h)

- `test_epistemic_as_of_filter` — filters superseded nodes
- `test_epistemic_layer_scoring` — memory decay, corroboration boost
- `test_epistemic_lazy_synthesis` — fire-and-forget, backoff counter
- `test_epistemic_hints` — belief candidates detected
- `test_recall_regression` — existing behavior unchanged

### Step 6: Delete sage/recall.py (30m)

- Remove from `sage/__init__.py` exports
- Delete file
- Run `just check` to verify no import errors

**Total: ~6 hours**

## What sage/recall.py Becomes

After extraction:
- `sage/recall.py` becomes a thin wrapper that calls FusionRetriever + epistemic pipeline
- Or: delete entirely, keep only `retrieval/epistemic.py`

Recommend: **Delete after extraction.** No point keeping a wrapper when the parts are wired directly.

## Resolved Questions

### Q1: Layer Enum Consolidation

**Decision: Keep `models/mcp.py:Layer` as canonical.**

- `models/mcp.py:Layer` — used by MCP tools, reranking, context_query (production)
- `sage/recall.py:Layer` — DELETE when extracting epistemic module
- `primitives.protocols.Layer` — external package, leave alone

No migration needed — consolidation naturally deletes the duplicate.

### Q2: FusedResult vs RecallResultItem

**Decision: Use `FusedResult`, extend minimally.**

FusedResult already has: `node_id, rrf_score, content, layer, confidence, conflict_status, created_at, tags`

Add one field:
```python
@dataclass
class FusedResult:
    # existing fields...
    properties: dict[str, Any] = field(default_factory=dict)  # ADD for arbitrary metadata
```

Skip for now:
- `confidence_breakdown` — nice-to-have, not essential
- `related` — depth traversal handled separately in context_query
- `synthesized` — add to response envelope, not per-result

### Q3: Scoring Constants Location

| Constant | Move to | Reason |
|----------|---------|--------|
| `MEMORY_DECAY_SIGMA` | `settings.py` | Tunable, affects scoring |
| `MAX_GRAPH_DEPTH` | `settings.py` | Tunable, affects traversal |
| `LAZY_SYNTHESIS_TIMEOUT_MS` | DELETE | Fire-and-forget, no timeout |
| `PPR_TOP_K_ANCHORS` | `retrieval/ppr.py` | PPR-specific |
| `PPR_DEFAULT_SCORE` | `retrieval/ppr.py` | PPR-specific |

## Success Criteria

- `recall(query, as_of="2026-06-15")` returns only nodes valid at that time
- `recall(query, include_hints=True)` returns belief candidate hints when applicable
- Lazy synthesis fires in background, returns `synthesis_pending: true`
- No regression on recall latency (<250ms p95 without hints)
- sage/recall.py deleted, no orphan code
