# as_of Time-Travel for Node ID Retrieval

## Summary

Enable `context_recall(node_ids=[...], as_of="...")` to return nodes filtered by temporal validity windows. Currently returns `as_of_not_supported` error.

## Behavior

For each requested node ID at `as_of` timestamp T:

| Condition | Response |
|-----------|----------|
| Node valid at T | Full node data |
| `valid_from > T` | `{error: "not_yet_valid", node_id, valid_from}` |
| `valid_to <= T` | `{error: "node_expired", node_id, valid_to, superseded_by}` |
| Node doesn't exist | `{error: "node_not_found", node_id}` |

**Validity check:** `(valid_from IS NULL OR valid_from <= T) AND (valid_to IS NULL OR valid_to > T)`

Nodes without `valid_from` are treated as valid from epoch (always valid unless expired).

## Implementation

### 1. New Cypher query `GET_NODES_BY_IDS_TEMPORAL` in `db/queries.py`

```cypher
UNWIND $node_ids AS nid
OPTIONAL MATCH (n {id: nid, silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL
OPTIONAL MATCH (n)-[:SUPERSEDES]->(successor)
RETURN 
    nid AS requested_id,
    n.id AS node_id,
    n.content AS content,
    labels(n) AS labels,
    n.confidence AS confidence,
    n.valid_from AS valid_from,
    n.valid_to AS valid_to,
    n.created_at AS created_at,
    n.committed AS committed,
    successor.id AS superseded_by
```

Classification logic (in Python, not Cypher):
- `node_id IS NULL` → `node_not_found`
- `committed = false` → `node_not_found` (treat uncommitted as nonexistent)
- `valid_from > as_of` → `not_yet_valid`
- `valid_to IS NOT NULL AND valid_to <= as_of` → `node_expired`
- Otherwise → valid, return full node

### 2. New service method in `services/context.py`

```python
async def get_temporal(
    self,
    node_ids: list[uuid.UUID],
    silo_id: uuid.UUID,
    as_of: datetime,
) -> list[dict[str, Any]]:
    """Fetch nodes by ID with temporal validity filtering."""
```

### 3. Update `context_get.py`

- Parse `as_of` ISO8601 string, normalize to UTC
- Call `ctx_svc.get_temporal()` instead of returning error
- Build mixed response array (valid nodes + error entries)

### 4. Update tests

- Remove xfail from: `test_recall_time_travel`, `test_recall_as_of_future`, `test_recall_as_of_iso8601`
- Add tests for: `not_yet_valid`, `node_expired` with `superseded_by`, NULL `valid_from` handling

## Response Format

```json
{
  "nodes": [
    {"node_id": "...", "content": "...", "valid_from": "...", "valid_to": null, ...},
    {"error": "not_yet_valid", "node_id": "...", "valid_from": "2026-06-01T00:00:00Z"},
    {"error": "node_expired", "node_id": "...", "valid_to": "2026-01-01T00:00:00Z", "superseded_by": "abc-123"}
  ]
}
```

## Files Changed

- `src/context_service/db/queries.py` — new query
- `src/context_service/services/context.py` — new `get_temporal()` method
- `src/context_service/mcp/tools/context_get.py` — wire temporal fetch, UTC normalization
- `tests/e2e/test_mcp_tools.py` — remove xfails, add edge cases
- `tests/evals/test_mcp_layers.py` — check for related xfails

## Edge Cases

- **NULL valid_from**: Treat as valid from epoch (node predates temporal tracking)
- **Uncommitted nodes**: Treat as nonexistent
- **Tombstoned nodes**: Filtered out (not returned even if valid at T)
- **Timezone handling**: All `as_of` inputs normalized to UTC before comparison
