# as_of Time-Travel for Node IDs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable `context_recall(node_ids=[...], as_of="...")` to return nodes filtered by temporal validity windows.

**Architecture:** Add Cypher query for batch ID lookup with temporal metadata, service method to classify results by validity, wire into existing context_get tool replacing the error stub.

**Tech Stack:** Python 3.12, Memgraph (Cypher), pytest

---

## File Structure

| File | Responsibility |
|------|----------------|
| `src/context_service/db/queries.py` | New `GET_NODES_BY_IDS_TEMPORAL` Cypher query |
| `src/context_service/services/context.py` | New `get_temporal()` method with classification logic |
| `src/context_service/mcp/tools/context_get.py` | Wire temporal fetch, UTC normalization |
| `tests/e2e/test_mcp_tools.py` | Remove xfails, add edge case tests |

---

### Task 1: Add Cypher Query

**Files:**
- Modify: `src/context_service/db/queries.py` (after line 678, before supersession section)

- [ ] **Step 1: Add the query constant**

Add after `TEMPORAL_QUERY_FILTERED` (around line 678):

```python
# --- Temporal fetch by explicit node IDs ---
# Returns all requested nodes with temporal metadata for classification.
# Classification (valid/not_yet_valid/expired/not_found) done in Python.

GET_NODES_BY_IDS_TEMPORAL = """
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
    n.layer AS layer,
    n.summary AS summary,
    n.tags AS tags,
    n.source_uri AS source_uri,
    n.content_hash AS content_hash,
    successor.id AS superseded_by
"""
```

- [ ] **Step 2: Commit**

```bash
git add src/context_service/db/queries.py
git commit -m "feat(db): add GET_NODES_BY_IDS_TEMPORAL query"
```

---

### Task 2: Add Service Method with Classification Logic

**Files:**
- Modify: `src/context_service/services/context.py` (add method after `get()`, around line 1080)

- [ ] **Step 1: Add import for the new query**

At top of file, add to the imports from `db.queries`:

```python
from context_service.db.queries import GET_NODES_BY_IDS_TEMPORAL
```

- [ ] **Step 2: Add the get_temporal method**

Add after the existing `get()` method (around line 1080):

```python
async def get_temporal(
    self,
    node_ids: list[uuid.UUID],
    silo_id: uuid.UUID,
    as_of: datetime,
) -> list[dict[str, Any]]:
    """Fetch nodes by ID with temporal validity filtering.

    Args:
        node_ids: List of node UUIDs to fetch.
        silo_id: Silo to scope the lookup.
        as_of: Point-in-time for validity check (must be UTC).

    Returns:
        List of dicts, each either a full node or an error entry:
        - Valid node: {node_id, content, layer, ...}
        - not_yet_valid: {error, node_id, valid_from}
        - node_expired: {error, node_id, valid_to, superseded_by}
        - node_not_found: {error, node_id}
    """
    from context_service.db.queries import GET_NODES_BY_IDS_TEMPORAL

    rows = await self._memgraph.execute_query(
        GET_NODES_BY_IDS_TEMPORAL,
        {
            "node_ids": [str(nid) for nid in node_ids],
            "silo_id": str(silo_id),
        },
    )

    results: list[dict[str, Any]] = []
    for row in rows:
        requested_id = row["requested_id"]
        node_id = row.get("node_id")

        # Node doesn't exist
        if node_id is None:
            results.append({"error": "node_not_found", "node_id": requested_id})
            continue

        # Uncommitted nodes treated as nonexistent
        if row.get("committed") is False:
            results.append({"error": "node_not_found", "node_id": requested_id})
            continue

        valid_from = row.get("valid_from")
        valid_to = row.get("valid_to")

        # Not yet valid: valid_from > as_of
        if valid_from is not None:
            # Handle both datetime and string formats from Memgraph
            vf = valid_from if isinstance(valid_from, datetime) else datetime.fromisoformat(str(valid_from).replace("Z", "+00:00"))
            if vf > as_of:
                results.append({
                    "error": "not_yet_valid",
                    "node_id": requested_id,
                    "valid_from": vf.isoformat(),
                })
                continue

        # Expired: valid_to <= as_of
        if valid_to is not None:
            vt = valid_to if isinstance(valid_to, datetime) else datetime.fromisoformat(str(valid_to).replace("Z", "+00:00"))
            if vt <= as_of:
                results.append({
                    "error": "node_expired",
                    "node_id": requested_id,
                    "valid_to": vt.isoformat(),
                    "superseded_by": row.get("superseded_by"),
                })
                continue

        # Valid node
        results.append({
            "node_id": node_id,
            "content": row.get("content"),
            "type": row.get("labels", ["Document"])[0] if row.get("labels") else "Document",
            "layer": row.get("layer"),
            "summary": row.get("summary"),
            "confidence": row.get("confidence"),
            "tags": row.get("tags"),
            "source_uri": row.get("source_uri"),
            "content_hash": row.get("content_hash"),
            "valid_from": valid_from.isoformat() if isinstance(valid_from, datetime) else valid_from,
            "valid_to": valid_to.isoformat() if isinstance(valid_to, datetime) else valid_to,
            "created_at": row.get("created_at").isoformat() if isinstance(row.get("created_at"), datetime) else row.get("created_at"),
            "silo_id": str(silo_id),
        })

    return results
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/services/context.py
git commit -m "feat(service): add get_temporal() for time-travel by node IDs"
```

---

### Task 3: Wire Temporal Fetch into context_get.py

**Files:**
- Modify: `src/context_service/mcp/tools/context_get.py:43-47` (replace error stub)

- [ ] **Step 1: Add datetime imports at top of file**

```python
from datetime import UTC, datetime
```

- [ ] **Step 2: Replace the as_of error stub with temporal fetch logic**

Replace lines 43-47:

```python
    if as_of is not None:
        return {
            "error": "as_of_not_supported",
            "message": "Point-in-time retrieval is not yet implemented",
        }
```

With:

```python
    if as_of is not None:
        # Parse and normalize to UTC
        try:
            parsed = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            as_of_dt = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        except ValueError:
            return {
                "error": "invalid_as_of_format",
                "message": "as_of must be an ISO 8601 datetime string (e.g. 2026-04-01T00:00:00Z)",
            }

        _start = time.perf_counter()
        auth = await get_mcp_auth_context()
        ctx_svc = get_context_service()

        if isinstance(node_ids, str):
            node_ids = [node_ids]

        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
            try:
                resolved_silo_id = uuid.UUID(silo_id)
            except ValueError:
                return {"error": "invalid_silo_id", "silo_id": silo_id}
        else:
            resolved_silo_id = derive_silo_id(auth.org_id)

        # Parse node IDs
        node_uuids: list[uuid.UUID] = []
        invalid_ids: list[dict[str, Any]] = []
        for nid in node_ids:
            try:
                node_uuids.append(uuid.UUID(nid))
            except ValueError:
                invalid_ids.append({"error": "invalid_node_id", "node_id": nid})

        if not node_uuids:
            CONTEXT_GET_LATENCY.observe(time.perf_counter() - _start)
            return {"nodes": invalid_ids}

        temporal_results = await ctx_svc.get_temporal(node_uuids, resolved_silo_id, as_of_dt)
        nodes_out = invalid_ids + temporal_results

        CONTEXT_GET_LATENCY.observe(time.perf_counter() - _start)
        return {"nodes": nodes_out}
```

- [ ] **Step 3: Commit**

```bash
git add src/context_service/mcp/tools/context_get.py
git commit -m "feat(mcp): wire as_of temporal fetch in context_get"
```

---

### Task 4: Remove xfail Markers and Update Tests

**Files:**
- Modify: `tests/e2e/test_mcp_tools.py:205, 217, 400`

- [ ] **Step 1: Remove xfail from test_recall_time_travel (line 205)**

Change:
```python
    @pytest.mark.xfail(reason="as_of with node_ids not yet implemented")
    async def test_recall_time_travel(self, mcp_client: Any) -> None:
```

To:
```python
    async def test_recall_time_travel(self, mcp_client: Any) -> None:
```

- [ ] **Step 2: Remove xfail from test_recall_as_of_future (line 217)**

Change:
```python
    @pytest.mark.xfail(reason="as_of with node_ids not yet implemented")
    async def test_recall_as_of_future(self, mcp_client: Any) -> None:
```

To:
```python
    async def test_recall_as_of_future(self, mcp_client: Any) -> None:
```

- [ ] **Step 3: Remove xfail from test_recall_as_of_iso8601 (line 400)**

Change:
```python
    @pytest.mark.xfail(reason="as_of not yet implemented for node_ids retrieval")
    async def test_recall_as_of_iso8601(self, mcp_client: Any) -> None:
```

To:
```python
    async def test_recall_as_of_iso8601(self, mcp_client: Any) -> None:
```

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_mcp_tools.py
git commit -m "test: remove as_of xfail markers (feature implemented)"
```

---

### Task 5: Add Edge Case Tests

**Files:**
- Modify: `tests/e2e/test_mcp_tools.py` (add to TestTimeTravel class, after existing tests)

- [ ] **Step 1: Add test for not_yet_valid error**

```python
    async def test_recall_as_of_before_node_created(self, mcp_client: Any) -> None:
        """Query with as_of before node's valid_from returns not_yet_valid."""
        # Store a node (will have valid_from = now)
        store_result = await store(mcp_client, "memory", "future node content")
        node_id = store_result["node_id"]

        # Query with as_of in the past (before node existed)
        past = "2020-01-01T00:00:00Z"
        result = await recall(mcp_client, node_ids=[node_id], as_of=past)

        assert "nodes" in result
        assert len(result["nodes"]) == 1
        node_result = result["nodes"][0]
        assert node_result.get("error") == "not_yet_valid"
        assert node_result.get("node_id") == node_id
        assert "valid_from" in node_result
```

- [ ] **Step 2: Add test for invalid as_of format**

```python
    async def test_recall_as_of_invalid_format(self, mcp_client: Any) -> None:
        """Invalid as_of format returns error."""
        store_result = await store(mcp_client, "memory", "test content")
        node_id = store_result["node_id"]

        result = await recall(mcp_client, node_ids=[node_id], as_of="not-a-date")

        assert result.get("error") == "invalid_as_of_format"
```

- [ ] **Step 3: Run the tests**

```bash
uv run pytest tests/e2e/test_mcp_tools.py::TestTimeTravel -v
```

Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_mcp_tools.py
git commit -m "test: add as_of edge case tests (not_yet_valid, invalid format)"
```

---

### Task 6: Restart Docker and Run Full E2E Suite

- [ ] **Step 1: Restart the app container to pick up changes**

```bash
docker restart context-service-app
sleep 5
```

- [ ] **Step 2: Run the full e2e test suite**

```bash
uv run pytest tests/e2e/test_mcp_tools.py -v
```

Expected: All tests pass (no xfails related to as_of)

- [ ] **Step 3: Run typecheck**

```bash
just typecheck
```

Expected: No errors

- [ ] **Step 4: Final commit if any fixes needed**

```bash
git status
# If any fixes were made, commit them
```

---

## Verification Checklist

- [ ] `context_recall(node_ids=[...], as_of="...")` returns valid nodes
- [ ] Nodes created after `as_of` return `not_yet_valid` error
- [ ] Invalid `as_of` format returns `invalid_as_of_format` error
- [ ] All e2e tests pass
- [ ] Typecheck passes
