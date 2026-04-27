# Phase 2: Time-Travel Queries

> "What did I know on date Y?" — query historical epistemic state.

## Goal

Enable agents to query the knowledge graph as it existed at a specific point in time, using bi-temporal fields already present on all nodes.

## User Story

```
Agent: context_lookup("OAuth token expiry", as_of="2026-04-01")
→ "OAuth tokens expire in 7 days" (superseded on 2026-04-15)

Agent: context_lookup("OAuth token expiry")  # current
→ "OAuth tokens expire in 30 days"
```

## Bi-Temporal Model

Every node has:

| Field | Meaning |
|-------|---------|
| `valid_from` | When this fact became true in the real world |
| `valid_to` | When this fact stopped being true (null = still valid) |
| `created_at` | When we learned this fact (system time) |

**Time-travel query**: Find nodes where `valid_from <= as_of < valid_to`

## MCP Tool Extension

### `context_lookup` (extended)

**Input**:
```json
{
  "query": "OAuth token expiry",
  "as_of": "2026-04-01T00:00:00Z",  // optional, defaults to now
  "limit": 10
}
```

**Output**:
```json
{
  "results": [
    {
      "node_id": "fact-old",
      "content": "OAuth tokens expire in 7 days",
      "confidence": 0.85,
      "valid_from": "2026-03-01T00:00:00Z",
      "valid_to": "2026-04-15T00:00:00Z",
      "superseded_by": "fact-new"
    }
  ],
  "as_of": "2026-04-01T00:00:00Z",
  "note": "Historical query — results reflect state at specified time"
}
```

## Implementation

### Cypher Query Modification

Current:
```cypher
MATCH (n:Fact)
WHERE n.embedding IS NOT NULL
  AND n.silo_id = $silo_id
RETURN n
```

With time-travel:
```cypher
MATCH (n:Fact)
WHERE n.embedding IS NOT NULL
  AND n.silo_id = $silo_id
  AND n.valid_from <= $as_of
  AND (n.valid_to IS NULL OR n.valid_to > $as_of)
RETURN n
```

### Code Changes

- `src/context_service/mcp/tools/lookup.py` — add `as_of` parameter
- `src/context_service/engine/retrieval.py` — pass temporal filter to query builder
- `src/context_service/db/queries.py` — modify all retrieval queries to accept temporal bounds

### Edge Cases

1. **`as_of` in the future**: Return current state with warning
2. **`as_of` before any data**: Return empty results
3. **Null `valid_to`**: Treat as still-valid (infinity)
4. **Supersession chains**: Include `superseded_by` pointer in response

## Testing

```python
def test_time_travel_returns_old_value():
    """Query before supersession returns original fact"""
    
def test_time_travel_returns_current_after_supersession():
    """Query after supersession returns new fact"""
    
def test_time_travel_at_exact_boundary():
    """Query at valid_from timestamp includes node"""
    
def test_time_travel_future_date():
    """Query with future date returns current state"""
```

## Effort Estimate

| Task | Estimate |
|------|----------|
| Query modification | 2 hours |
| MCP tool extension | 1 hour |
| Response schema update | 1 hour |
| Tests | 2 hours |
| Edge case handling | 2 hours |
| **Total** | **8 hours** |

## Dependencies

- Bi-temporal fields must be populated (already are)
- Supersession edges should set `valid_to` on superseded node

## Success Criteria

- [ ] `context_lookup` accepts `as_of` parameter
- [ ] Returns nodes valid at that timestamp
- [ ] Excludes nodes superseded before that timestamp
- [ ] Response indicates this is a historical query
