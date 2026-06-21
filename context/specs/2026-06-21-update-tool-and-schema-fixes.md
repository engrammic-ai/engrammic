# Update Tool and Schema Fixes

Date: 2026-06-21
Status: Design approved, pending implementation
Related: context/specs/2026-06-21-eag-theory-gap-audit.md (GAP-004, GAP-006)

## Overview

Three coordinated changes to improve supersession UX and close spec gaps:

1. **`update` MCP tool** — explicit supersession verb with built-in search
2. **`status` field** — primitives schema change for node lifecycle state
3. **R2 threshold fix** — align primitives to spec (3+ sources for Fact promotion)

## 1. `update` Tool

### Purpose

Reduce duplicate knowledge creation by making supersession explicit. Current flow requires agents to manually extract node IDs from `recall` results and pass `supersedes` param to `learn`. Agents frequently forget, creating duplicates the custodian must clean up.

### Interface

```python
async def update(
    content: str,
    evidence: list[str],
    *,
    query: str | None = None,      # semantic search for target
    target: str | None = None,     # explicit node_id (skips search)
    source_tier: str | None = None,
    confidence: float = 0.8,
) -> UpdateResult
```

### Scope

Knowledge-layer only (Claims). Memory nodes use `remember` with `supersedes` param.

### Behavior Matrix

| Input | Action |
|-------|--------|
| `target` provided | Direct supersession, no search |
| `target` is already superseded | Error: "Cannot update already-superseded node. Use its successor." |
| `query` provided, 1 match | Auto-supersede the match |
| `query` provided, 2+ matches | Return ambiguous with candidates |
| `query` provided, 0 matches | Return not_found, suggest `learn` |
| Neither provided | Error |

"1 match" = exactly one result above 0.7 similarity threshold. "2+ matches" = multiple results above threshold.

### Return Types

```python
# Success
{
    "status": "updated",
    "node_id": "uuid",
    "superseded_id": "uuid",
    "superseded_content": "first 200 chars..."
}

# Ambiguous (agent must pick)
{
    "status": "ambiguous",
    "candidates": [
        {"id": "uuid", "content": "snippet...", "similarity": 0.85, "created_at": "iso"},
        ...
    ]
}

# Not found
{
    "status": "not_found",
    "message": "No existing knowledge matches query. Use learn() to create new."
}
```

### Candidate Selection

- Top 3 by similarity score
- Minimum threshold: 0.7
- Returns content snippet (first 200 chars) so agent can pick without another recall
- Ordered by similarity descending

### Latency

| Scenario | Flow | Latency |
|----------|------|---------|
| Single match | search + auto-supersede | ~550ms |
| Multiple matches | search + return + second call | ~850ms |
| Zero matches | search + error | ~250ms |

Same as current manual flow for happy path (single match).

## 2. `status` Field

### Schema Change (primitives)

```python
class NodeStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    TOMBSTONED = "tombstoned"
```

Added to all content node dataclasses: `Memory`, `Claim`, `Fact`, `Belief`, `Commitment`.

Default: `NodeStatus.ACTIVE`

### Graph Storage

- Property: `properties.status`
- Index: `CREATE INDEX ON :Claim(properties.status)` (per label)

### Lifecycle Transitions

| Event | Status Change |
|-------|---------------|
| Node created | `active` |
| Node superseded | `active` -> `superseded` |
| Node forgotten (tombstoned) | `active` -> `tombstoned` |
| Superseded node forgotten | `superseded` -> `tombstoned` |

### Query Behavior

- Default: `WHERE n.properties.status = 'active'`
- `recall(include_inactive=True)` — includes superseded and tombstoned nodes
- `history(node_id)` — walks chain regardless of status

### Migration

```cypher
// Backfill superseded from edges
MATCH (old)<-[:SUPERSEDES]-(new)
WHERE old.properties.status IS NULL OR old.properties.status = 'active'
SET old.properties.status = 'superseded';

// Backfill active on remaining
MATCH (n)
WHERE n.properties.status IS NULL
SET n.properties.status = 'active';
```

Alembic migration with Memgraph execution.

## 3. R2 Threshold Fix

### Change (primitives)

```python
# primitives/eag/epistemology/promotion.py

def should_promote_r2(claims: list[ClaimForPromotion]) -> PromotionDecision:
    if len(claims) < 3:  # was: < 2
        return PromotionDecision(
            should_promote=False,
            rule=None,
            reason=f"R2 requires >= 3 sources, got {len(claims)}",
        )
```

### Rationale

- EAG Definition A.3 specifies 3+ independent sources for Fact
- Context-service `PROMOTION_THRESHOLD = 3` already correct
- Primitives R2 rule was inconsistent at 2

### Impact

- Forward-looking only; existing Facts unaffected
- Claims needing promotion now require third corroborating source
- Higher trust bar for Fact status

## Implementation Order

| Step | Repo | Change |
|------|------|--------|
| 1 | primitives | Add `NodeStatus` enum and `status` field to node dataclasses |
| 2 | primitives | Fix R2 threshold to 3 |
| 3 | primitives | Release to PyPI |
| 4 | context-service | Add `update` MCP tool |
| 5 | context-service | Migration to backfill status |
| 6 | context-service | Update queries to filter by status |
| 7 | context-service | Pin to new primitives version |

Steps 1-2 can be one primitives PR. Steps 4-6 can be one context-service PR after primitives release.

## Testing

### `update` tool
- Single match auto-supersedes
- Multiple matches returns candidates with `similarity` scores
- Zero matches returns not_found
- Direct target bypasses search
- Target already superseded returns error
- Superseded node gets `status=superseded`

### `status` field
- New nodes have `status=active`
- Supersession sets old node to `superseded`
- Forget sets node to `tombstoned`
- Superseded node can be tombstoned (`superseded` -> `tombstoned`)
- Default queries exclude non-active
- `include_inactive=True` includes superseded and tombstoned

### R2 threshold
- 2 claims do not promote
- 3+ claims with authoritative source promote
- Aggregate confidence threshold (0.8) still applies

## Gaps Closed

- **GAP-004**: `status=superseded` field enables systematic enumeration of superseded nodes
- **GAP-006**: R2 threshold aligned to spec (3+ sources)
- **Implicit**: Reduced duplicates via explicit `update` verb
