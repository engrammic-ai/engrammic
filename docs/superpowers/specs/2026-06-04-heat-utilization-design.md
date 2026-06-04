# Heat Utilization and Long-Horizon Memory Fixes

## Summary

Fix long-horizon memory recall and optimize token usage for the Somnus benchmark through two changes: brain path decay floor and tier-driven summary defaults.

## Problem Statement

1. **Brain path decay kills long-horizon recall:** The brain path (`sage/recall.py`) uses Gaussian decay with no floor. A 365-day-old memory scores 0.03% of its similarity, effectively invisible. The live path (`signals/freshness.py`) has a floor of 0.25 and weighted blend, retaining ~77% for old memories.

2. **Token waste on cold nodes:** All recall results return full content by default. COLD nodes (87% of scored nodes) are rarely relevant but consume 500-2000 tokens each.

## Design

### Phase 1: Benchmark Fixes (This Spec)

#### 1. Brain Path Decay Floor

**File:** `src/context_service/sage/recall.py`

**Current:**
```python
if layer == Layer.MEMORY:
    layer_score = similarity * gaussian_decay(age_days)
```

**After:**
```python
from context_service.signals.freshness import compute_freshness

# MEMORY_DECAY_SIGMA = 90 (existing constant in sage/recall.py)
# Wider than live path's 30d — intentional for long-horizon epistemic recall

if layer == Layer.MEMORY:
    freshness = compute_freshness(created_at_dt, now, sigma_days=MEMORY_DECAY_SIGMA)
    layer_score = similarity * ((1.0 - settings.freshness_weight) + settings.freshness_weight * freshness)
```

**Rationale:**
- Reuses existing `compute_freshness` which has floor=0.25 built in
- Pulls weight from settings (not hardcoded) to stay in sync with live path
- Keeps existing `MEMORY_DECAY_SIGMA = 90` constant (wider than live path's 30d for long-horizon)
- Requires passing datetime instead of pre-computed age_days

**Weight semantics:** At `freshness_weight=0.3` (default):
- Fresh node (freshness=1.0): score = similarity * 1.0
- Old node (freshness=0.25 floor): score = similarity * 0.775
- This matches the live path convention in `services/context.py:1532`

**Behavior change:**
| Age | Before | After |
|-----|--------|-------|
| 30d | 94.6% | 98.4% |
| 90d | 60.7% | 88.2% |
| 180d | 13.5% | 79.1% |
| 365d | 0.03% | 77.5% |

#### 2. Tier-Driven Summary Default

**Files:** `src/context_service/mcp/tools/context_query.py`, `context_recall.py`

**Current:**
- All nodes return full `content` by default
- Caller must pass `include_content=False` for summaries

**After:**
- HOT/WARM nodes: return full content (unchanged)
- COLD nodes: return summary by default
- Caller can override with `include_content=True`

**Implementation:**
```python
def _format_result(node_props, include_content=None):
    tier = node_props.get("tier", "COLD")  # Default COLD for unscored nodes (safe)
    
    if include_content is None:
        include_content = tier in ("HOT", "WARM")
    
    base = {
        "node_id": node_props["id"],
        "layer": node_props.get("layer"),
        "relevance_score": node_props.get("relevance_score"),
        "created_at": node_props.get("created_at"),
        "tier": tier,
    }
    
    if include_content:
        return {**base, "content": node_props["content"]}
    else:
        summary = node_props.get("summary") or node_props["content"][:200]
        return {**base, "summary": summary, "expandable": True}
```

**Override mechanism:** The `include_content` param is passed through from the MCP tool call:
- `recall(query="...", include_content=True)` forces full content for all results
- `recall(query="...", include_content=False)` forces summaries for all results
- `recall(query="...")` (default) uses tier-based logic

**Risk mitigation:**
- `node_id` always returned for expand-on-demand
- `expandable: True` signals to caller that full content is available
- Benchmark can pass `include_content=True` to get full content if needed

**Known limitation:** 200-char truncation fallback produces low-quality summaries for nodes with important content after char 200. Addressed in Phase 2 via pre-computed summaries.

**Token savings:** COLD nodes drop from ~500-2000 tokens to ~50-200 tokens each.

### Phase 2: Architecture Cleanup (Deferred)

Not in scope for this spec. To be planned post-benchmark:

1. Pre-computed summaries on write (avoid 200-char truncation fallback)
2. Heat affecting Qdrant retrieval (requires payload schema change + reindex)
3. Decay constant alignment documentation (7d heat / 30d freshness / 90d brain)

## Testing

1. **Unit tests:**
   - `test_sage_recall.py`: verify 365-day memory scores ~77% not ~0%
   - `test_context_query.py`: verify COLD nodes return summary, HOT/WARM return content

2. **Integration test:**
   - Seed nodes with old timestamps, verify they surface in recall results

3. **Manual verification:**
   - Run recall on beta, confirm old nodes appear with expected scores

## Rollout

1. Implement decay floor fix
2. Implement tier-driven summary
3. Deploy to beta
4. Run Somnus benchmark
5. Iterate if needed

## Success Criteria

- Long-horizon memory test: year-old memories surface with >50% of similarity score
- Token usage: average tokens per recall drops 30-50% from baseline

**Baseline measurement (before implementation):**
- Run 10 representative recall queries on beta
- Record average response size in tokens
- Use as comparison point post-implementation
