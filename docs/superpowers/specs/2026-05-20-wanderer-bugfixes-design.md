# Wanderer Bugfixes Design

**Date:** 2026-05-20  
**Status:** Approved  
**Scope:** Fix 3 bugs discovered by wanderer exploration

## Background

Codebase exploration on 2026-05-20 discovered three bugs in the belief/revision subsystem:

1. **ID collision in revise/split** - `_make_revised_belief_id` produces identical IDs for revised beliefs and split children under certain conditions
2. **magnitude_pct always 0.0** - Auto-reflection records 0.0% drift regardless of actual cosine distance
3. **Naive word overlap** - Belief merge uses word co-occurrence, triggering false positives on common words

## Bug 1: ID Collision in revise/split

### Problem

`_make_revised_belief_id(old_belief_id, revision_count)` hashes `revision:{old_belief_id}:{revision_count}`.

- `revise_belief` calls with `revision_count` from DB (1, 2, 3...)
- `split_belief` calls with `i + 1` where `i` is child index (1, 2...)

If a belief is revised once (`revision_count=1`) then split, child 0 gets `revision:{id}:1` which collides with the existing revised belief. Memgraph MERGE silently overwrites.

### Solution

Add `operation` parameter to disambiguate:

```python
def _make_revised_belief_id(
    old_belief_id: str, 
    counter: int, 
    operation: Literal["revision", "split"] = "revision"
) -> str:
    return hashlib.blake2b(
        f"{operation}:{old_belief_id}:{counter}".encode(), digest_size=32
    ).hexdigest()
```

- `revise_belief` passes `operation="revision"`
- `split_belief` passes `operation="split"`

No migration required - new IDs will differ from any existing IDs.

### Files

- `src/context_service/engine/revision.py`

## Bug 2: magnitude_pct Always 0.0

### Problem

`revise_belief()` hardcodes `magnitude_pct = 0.0` (line 442). The comment acknowledges this is a placeholder. The actual cosine distance IS computed by `check_belief_revision()` before `revise_belief()` is called, but is not passed through.

The MetaObservation created by `create_auto_reflection` always says "0.0% shift" regardless of actual drift.

### Solution

Add `cosine_distance: float = 0.0` parameter to `revise_belief()`. Callers pass the value from `RevisionCheckResult.cosine_distance`.

```python
async def revise_belief(
    store: HyperGraphStore,
    old_belief_id: str,
    new_content: str,
    silo_id: str,
    embedding_client: EmbeddingService,
    cosine_distance: float = 0.0,  # NEW
) -> str:
    ...
    magnitude_pct = cosine_distance * 100  # Convert to percentage
```

### Files

- `src/context_service/engine/revision.py` - signature change
- `src/context_service/custodian/identities/synthesizer.py` - pass distance from check result

## Bug 3: Naive Word Overlap

### Problem

`belief_merge.py` uses this Cypher to find overlapping beliefs:

```cypher
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
```

Any word longer than 4 characters appearing in 2+ beliefs triggers overlap detection. Common words like "their", "which", "about", "would", "could", "should", "because", "between" all pass the filter. This causes false merge candidates.

### Solution

Replace word co-occurrence with embedding cosine similarity. Beliefs already have `centroid_embedding` stored.

```cypher
MATCH (b1:Belief {silo_id: $silo_id}), (b2:Belief {silo_id: $silo_id})
WHERE b1.id < b2.id 
  AND (b1.status IS NULL OR b1.status <> 'stale')
  AND (b2.status IS NULL OR b2.status <> 'stale')
  AND b1.centroid_embedding IS NOT NULL 
  AND b2.centroid_embedding IS NOT NULL
WITH b1, b2, gds.similarity.cosine(b1.centroid_embedding, b2.centroid_embedding) AS sim
WHERE sim > $threshold
RETURN b1.id AS belief1, b2.id AS belief2, sim AS similarity
ORDER BY similarity DESC
LIMIT $max_pairs
```

Configuration:
- `threshold`: 0.85 default, configurable via `Settings.custodian.belief_merge_threshold`
- `max_pairs`: 50 per run

Fallback: Beliefs without embeddings are skipped (not merged).

### Files

- `src/context_service/pipelines/assets/belief_merge.py` - new Cypher query
- `src/context_service/config/settings.py` - add `belief_merge_threshold` setting

## Testing

### Unit Tests

1. **ID collision test**: Create a belief, revise it once, then split it. Assert all IDs are unique.
2. **magnitude_pct test**: Mock `check_belief_revision` to return distance=0.15, call `revise_belief`, verify MetaObservation contains "15.0%".
3. **Word overlap regression**: Ensure old word-based query is removed.

### Integration Tests

1. **Belief merge with embeddings**: Seed two beliefs with cosine similarity 0.9, run merge asset, verify they're flagged for merge.
2. **Belief merge below threshold**: Seed two beliefs with cosine similarity 0.7, run merge asset, verify they're NOT flagged.
3. **Missing embedding fallback**: Seed belief without embedding, verify it's skipped gracefully.

## Rollout

All changes are backward compatible. No migration needed. Deploy as single PR.

## References

- Wanderer findings stored in Engrammic tagged `engrammic-cs`
- `src/context_service/engine/revision.py:169` - ID generation
- `src/context_service/engine/revision.py:442` - magnitude placeholder
- `src/context_service/pipelines/assets/belief_merge.py:16` - word overlap query
