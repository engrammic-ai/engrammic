# Recall Epistemic Hooks

**Date:** 2026-06-20
**Status:** Spec
**Goal:** Bring back sage/recall.py epistemic features as post-retrieval hooks

## Context

When FusionRetriever replaced sage/recall.py, we gained multi-channel retrieval but lost three epistemic features:

1. **as_of time-travel** — query state at a past point in time
2. **Lazy synthesis** — auto-trigger belief formation when ready clusters are touched
3. **Belief candidate hints** — surface "this could become a belief" to the agent

These don't belong inside the retriever — they're post-retrieval concerns. Spec them as hooks in the recall pipeline.

## Current Pipeline

```
recall.py
  → _context_recall()
      → _context_query()
          → FusionRetriever.retrieve()   # 4-channel + RRF
          → apply_epistemic_fusion()      # confidence/conflict scoring
      → (result formatting)
  → (engagement detection)
  → (trust gate)
  → return
```

## Proposed Pipeline

```
recall.py
  → _context_recall()
      → _context_query()
          → FusionRetriever.retrieve()
          → apply_epistemic_fusion()
          → apply_temporal_filter()       # NEW: as_of filtering
      → (result formatting)
  → maybe_trigger_lazy_synthesis()        # NEW: synthesis hook
  → detect_epistemic_hints()              # NEW: belief candidate hints
  → (engagement detection)
  → (trust gate)
  → return
```

---

## Feature 1: as_of Time-Travel

**What it does:** Filter results to only nodes that existed and were valid at a specific past time.

**Use case:** "What did I know about X last Tuesday?" — agent wants historical state, not current.

### Interface

Add `as_of: str | None` param to recall tool:

```python
async def recall(
    query: str | None = None,
    ...
    as_of: str | None = None,  # ISO datetime or relative ("7d ago", "last tuesday")
) -> dict[str, Any]:
```

### Implementation

**Location:** `context_query.py` after FusionRetriever returns, before epistemic fusion.

```python
async def apply_temporal_filter(
    results: list[QueryResult],
    as_of: datetime,
    store: HyperGraphStore,
    silo_id: str,
) -> list[QueryResult]:
    """Filter results to state valid at as_of time.
    
    Keeps nodes where:
    - created_at <= as_of
    - valid_to is None OR valid_to > as_of
    
    For superseded nodes, walks the SUPERSEDES chain to find
    the version that was current at as_of.
    """
    filtered = []
    for r in results:
        # Skip if created after as_of
        if r.created_at and r.created_at > as_of:
            continue
        
        # Check valid_to (supersession)
        valid_to = r.properties.get("valid_to")
        if valid_to and parse_datetime(valid_to) <= as_of:
            # This version was already superseded at as_of
            # TODO: optionally walk chain to find valid version
            continue
        
        filtered.append(r)
    
    return filtered
```

**Parsing:** Reuse `retrieval/temporal.py` for NL parsing ("last tuesday" → datetime).

### Effort

2-3 hours

---

## Feature 2: Lazy Synthesis

**What it does:** When recall touches nodes in a cluster that's ready for synthesis but has no belief yet, trigger synthesis inline and include the new belief in results.

**Use case:** Agent recalls related facts → system realizes they should be a belief → synthesizes and returns it immediately.

### Interface

No new params. Behavior controlled by config:

```yaml
# settings.py
lazy_synthesis_enabled: bool = True
lazy_synthesis_timeout_ms: int = 2000
```

### Implementation

**Location:** `recall.py` after `_context_recall()` returns, before engagement detection.

**IMPORTANT: Fire-and-forget, not blocking.** The brainstorm decided lazy synthesis must not block recall. A 2s timeout destroys the 250ms recall latency target.

```python
async def maybe_trigger_lazy_synthesis(
    results: list[dict],
    silo_id: str,
    store: HyperGraphStore,
    llm: Any,
) -> tuple[list[dict], bool]:
    """Check if result nodes belong to synthesis-ready clusters.
    
    Returns:
        (results_unchanged, synthesis_pending)
        
    If a cluster is READY/STALE with no current_belief_id:
    - Fire off synthesis as background task (DO NOT await)
    - Return immediately with synthesis_pending=True
    - Agent will see the belief on next recall
    """
    from context_service.sage.transactions import synthesize
    
    node_ids = [r["node_id"] for r in results if r.get("node_id")]
    
    # Find clusters for these nodes
    clusters = await store.execute_query(
        GET_CLUSTERS_FOR_NODES,
        {"silo_id": silo_id, "node_ids": node_ids},
    )
    
    synthesis_pending = False
    
    for cluster in clusters:
        if cluster["state"] in ("READY", "STALE") and not cluster["current_belief_id"]:
            # Check attempt counter to prevent infinite retries
            attempts = cluster.get("synthesis_attempts", 0)
            if attempts >= 3:
                continue  # Backoff: stop trying after 3 failures
            
            # Fire-and-forget: schedule synthesis without blocking
            asyncio.create_task(
                _run_synthesis_with_backoff(
                    store, cluster["cluster_id"], silo_id, llm
                )
            )
            synthesis_pending = True
    
    return results, synthesis_pending


async def _run_synthesis_with_backoff(
    store: HyperGraphStore,
    cluster_id: str,
    silo_id: str,
    llm: Any,
) -> None:
    """Background synthesis with attempt tracking."""
    try:
        # Increment attempt counter first
        await store.execute_query(
            "MATCH (c:Cluster {id: $id}) SET c.synthesis_attempts = coalesce(c.synthesis_attempts, 0) + 1",
            {"id": cluster_id},
        )
        await synthesize(store, cluster_id, silo_id, llm)
        # On success, reset counter
        await store.execute_query(
            "MATCH (c:Cluster {id: $id}) SET c.synthesis_attempts = 0",
            {"id": cluster_id},
        )
    except Exception:
        # Failure is logged but doesn't propagate; counter stays incremented
        pass
```

**Response field:**
```json
{
  "results": [...],
  "synthesis_pending": true  // Synthesis running in background; check back later
}
```

**Key differences from blocking version:**
1. No `asyncio.wait_for` timeout
2. Uses `asyncio.create_task()` for true fire-and-forget
3. Results are NOT modified (no inline belief append)
4. Agent sees the belief on next recall, not this one
5. Backoff via `synthesis_attempts` counter prevents infinite loops

### Effort

3-4 hours

---

## Feature 3: Belief Candidate Hints

**What it does:** Detect when result nodes could form a belief (corroborated facts, ready clusters) and hint this to the agent.

**Use cases:**
- "These 3 facts corroborate each other — consider forming a belief"
- "This reasoning chain could be crystallized"
- "Related context exists that you haven't seen"

### Interface

Response includes `hints` array (already stubbed in recall.py):

```json
{
  "results": [...],
  "hints": [
    {
      "type": "belief_candidate",
      "message": "3 facts corroborate: API uses OAuth2",
      "node_ids": ["abc", "def", "ghi"],
      "action": "consider decide() to form belief"
    },
    {
      "type": "chain_continuation",
      "message": "Related reasoning chain exists",
      "chain_id": "xyz",
      "action": "recall with depth=1 to see connections"
    }
  ]
}
```

### Implementation

**Location:** `recall.py` after synthesis hook, controlled by `recall_hints_enabled` setting.

```python
async def detect_epistemic_hints(
    results: list[dict],
    query_embedding: list[float],
    silo_id: str,
    store: HyperGraphStore,
) -> list[dict]:
    """Detect belief candidates and chain continuations.
    
    Belief candidates:
    - Facts with same (subject, predicate) and corroboration_count >= 2
    - Clusters in READY state without beliefs
    
    Chain continuations:
    - Reasoning chains with embeddings similar to query
    - Chains that reference result nodes
    """
    hints = []
    
    # 1. Belief candidates from corroborated facts
    fact_ids = [r["node_id"] for r in results if r.get("layer") == "knowledge"]
    if fact_ids:
        corroborated = await store.execute_query(
            GET_CORROBORATED_FACTS,
            {"silo_id": silo_id, "node_ids": fact_ids, "min_corroboration": 2},
        )
        for group in corroborated:
            hints.append({
                "type": "belief_candidate",
                "message": f"{len(group['node_ids'])} facts corroborate: {group['summary']}",
                "node_ids": group["node_ids"],
                "action": "consider decide() to form belief",
            })
    
    # 2. Chain continuations (related reasoning)
    # Similar embedding search in Intelligence layer
    chains = await vector_search(
        query_embedding,
        layer="intelligence",
        silo_id=silo_id,
        top_k=3,
        min_similarity=0.7,
    )
    for chain in chains:
        if chain["node_id"] not in [r["node_id"] for r in results]:
            hints.append({
                "type": "chain_continuation", 
                "message": "Related reasoning chain exists",
                "chain_id": chain["node_id"],
                "action": "recall with depth=1 to see connections",
            })
    
    return hints
```

### Effort

4-5 hours

---

## Implementation Order

| Phase | Feature | Effort | Dependencies |
|-------|---------|--------|--------------|
| 1 | as_of time-travel | 2-3h | None |
| 2 | Belief candidate hints | 4-5h | None |
| 3 | Lazy synthesis | 3-4h | SAGE synthesize() working |

**Total:** 9-12 hours

Phase 1 is standalone and useful immediately. Phases 2-3 depend on SAGE pipeline health.

---

## Migration Path

1. Implement hooks in current pipeline
2. Add feature flags (all default off initially)
3. Enable in beta, monitor latency impact
4. Delete `sage/recall.py` once hooks are validated

---

## Resolved Questions

1. **Lazy synthesis latency:** ~~2s timeout blocks recall.~~ **RESOLVED: Fire-and-forget.** Use `asyncio.create_task()`, return immediately with `synthesis_pending=true`. Agent sees belief on next recall. Added backoff counter to prevent infinite retries.

2. **as_of + supersession:** **CLARIFIED: Two distinct features.**
   - **Filter out superseded nodes** (v1): O(1) check — `valid_to IS NULL OR valid_to > as_of`. This is sufficient for "don't show me things that were already superseded."
   - **Substitute historical versions** (v2): Requires SUPERSEDES chain walk to find the version that was current at `as_of`. This is a different, more expensive feature.
   
   **For v1, implement the simple filter.** Chain walk is only needed if we want to show "what was the belief at that time" rather than "what beliefs existed at that time."

3. **as_of + depth:** **RESOLVED: Filter at all depths.** When recall uses `depth=2`, both the root node AND neighbors must be filtered by `as_of`. The filter runs after graph traversal, filtering all returned nodes.

## Open Questions

1. **Hint frequency:** How often should we surface hints? Every recall? Only when confidence is high? Rate limit per session?

2. **Belief hints value:** 4-5h effort for uncertain value. Consider shipping as_of + lazy synthesis first, evaluate if hints are needed based on agent feedback.
