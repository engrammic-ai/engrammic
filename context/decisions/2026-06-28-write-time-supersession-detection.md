# Write-Time Supersession Detection

**Date:** 2026-06-28  
**Status:** Implemented  
**Related:** `src/context_service/engine/supersession_detection.py`

## Problem

Agents write updates without linking them to what they're updating. The supersession chain is lost because:
1. Agent must recall first to find existing node ID
2. Agent must explicitly pass `supersedes=<node_id>`
3. Semantic similarity alone can't determine intent (similar != replacement)

Result: duplicate nodes instead of version chains, broken provenance.

## Constraints

1. **Efficiency**: Can't add 500ms LLM calls to every write
2. **Precision**: Semantic similarity is necessary but not sufficient
3. **Intent**: Supersession is author intent, not a discoverable relationship
4. **Existing infra**: Already have embedding at write time, Qdrant search, SPO extraction

## Decision: Tiered Detection

Three tiers, escalating cost:

| Tier | Signal | Cost | Auto-supersede? |
|------|--------|------|-----------------|
| 0 | Session recall + subject match | ~1ms | Yes |
| 1 | SPO (S,P) match + different O + same agent | ~5ms | Yes (if same session OR <5min) |
| 2 | Semantic similarity (existing contradiction infra) | ~50ms | Never |

### Why this order?

**Tier 0 (session recall)** is highest confidence because it captures implicit intent: "I looked at X, now I'm writing about X" strongly suggests update. Uses existing `ACCESSED_BY` edges from recall tracking.

**Tier 1 (SPO match)** is deterministic: same subject + same predicate + different object + same agent = update by definition. No LLM needed. Requires SPO on both nodes (falls back to subject-only with lower confidence).

**Tier 2 (semantic)** is weakest signal. Two claims can be semantically similar but:
- Complementary, not replacing
- Different scopes/contexts
- Same fact from different perspectives

Never auto-supersedes. Returns candidates for agent decision.

### Auto-supersede thresholds

```
session_recall + subject_match               → auto (0.95 confidence)
spo_match + different_object + same_session  → auto (0.90+ confidence)
spo_match + different_object + <5min         → auto (0.90+ confidence)
spo_match + same_object                      → NO (duplicate, not update)
semantic_similarity_only                     → NO (candidate only)
```

### Why 5 minutes?

Arbitrary but reasonable: if an agent writes about the same (S,P) within 5 minutes with different O, it's almost certainly a correction. Outside that window, could be a legitimate new observation from changed reality.

Configurable via `auto_supersede_window_minutes`.

## 1:N Supersession

**Supported at edge level**: Nothing stops `(A)-[:SUPERSEDES]->(B)` and `(A)-[:SUPERSEDES]->(C)`.

**Not optimized at pointer level**: The linked-list (`tail_id`/`head_id`) only tracks one chain. First supersession "wins" for O(1) lookups. Others resolved via edge traversal.

Acceptable tradeoff: 1:N is rare, and the edges exist for provenance. Read path handles it via `FILTER_SUPERSEDED_AT` chain walk fallback.

## Alternatives Considered

### Alternative 1: LLM judge at write time

Pros: Could determine "does X supersede Y" with high accuracy  
Cons: 500ms+ per write, cost per write, overkill for most cases  
Rejected: Tier 1 SPO match handles the clear cases; ambiguous cases should go to agent anyway.

### Alternative 2: Batch reconciliation only (SAGE job)

Pros: No write-time overhead  
Cons: Supersession chains broken until batch runs (minutes), agent loses immediate feedback  
Decision: Keep as Tier 3 safety net but prioritize write-time for agent feedback.

### Alternative 3: Require explicit `supersedes` or `is_new` flag

Pros: Forces agent to think about it  
Cons: Breaking change, agents will just pass `is_new=True` to avoid thinking  
Rejected: Better to detect automatically and surface candidates.

## Configuration

```python
class SupersessionDetectionConfig:
    enabled: bool = True
    auto_supersede_enabled: bool = True
    semantic_fallback_enabled: bool = True
    similarity_threshold: float = 0.85
    auto_supersede_window_minutes: int = 5
```

## Response Shape

When detection runs and finds candidates:

```json
{
  "node_id": "new-uuid",
  "auto_superseded": "old-uuid",        // if auto-triggered
  "likely_updates": [{"id": "...", "subject": "...", "reason": "session_recall"}],
  "possible_updates": [{"id": "...", "reason": "semantic_similarity"}]
}
```

## Indexes Added

For Tier 1 performance:
- `CREATE INDEX ON :Claim(silo_id, subject);`
- `CREATE INDEX ON :Claim(silo_id, agent_id, subject);`
- Same for `:Fact` and `:Memory`
