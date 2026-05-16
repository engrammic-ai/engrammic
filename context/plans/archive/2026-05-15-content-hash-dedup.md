# Plan: Content-Hash Deduplication for Knowledge Layer

## Context

Currently, every call to `assert_claim()` creates a new Claim node, even if identical content already exists. This leads to duplicate claims in the knowledge layer. We want to deduplicate claims based on content hash so the same assertion isn't stored twice.

**Scope:** Knowledge layer only (not memories, which can legitimately repeat).

## Changes

### 1. Full SHA256 hash (no truncation)

**File:** `src/context_service/services/context.py:196`

```python
# Before
content_hash=hashlib.sha256(content.encode()).hexdigest()[:16]

# After
content_hash=hashlib.sha256(content.encode()).hexdigest()
```

### 2. Add content-hash dedup check in assert_claim()

**File:** `src/context_service/services/context.py` (in `assert_claim()`, before the `store()` call at line 1018)

Add a query to check for existing claim with same content_hash:

```python
# Compute content_hash before store() call
content_hash = hashlib.sha256(content.encode()).hexdigest()

# Check for existing claim with same content_hash in this silo
existing_rows = await self._memgraph.execute_query(
    """
    MATCH (c:Claim {silo_id: $silo_id, content_hash: $content_hash})
    WHERE c.tombstoned_at IS NULL
    RETURN c
    LIMIT 1
    """,
    {"silo_id": str(scope.silo_id), "content_hash": content_hash},
)

if existing_rows:
    logger.debug("assert_claim_content_hash_hit", content_hash=content_hash[:16])
    existing_node = self._row_to_node(existing_rows[0]["c"])
    
    # Still create evidence edges to accumulate corroboration
    ev_node_ids = [ev_ref[5:] for ev_ref in evidence if ev_ref.startswith("node:")]
    if ev_node_ids:
        from context_service.db.queries import BATCH_CREATE_DERIVED_FROM_EDGES
        await self._memgraph.execute_write(
            BATCH_CREATE_DERIVED_FROM_EDGES,
            {"claim_id": str(existing_node.id), "silo_id": str(scope.silo_id), "ev_ids": ev_ids},
        )
    
    return existing_node
```

Then pass the pre-computed `content_hash` to `store()` to avoid recomputing.

### 3. Update store() to accept optional content_hash

**File:** `src/context_service/services/context.py` (store() signature and body)

Add optional `content_hash` parameter so callers can pass pre-computed hash:

```python
async def store(
    self,
    scope: ScopeContext,
    content: str,
    node_type: str,
    *,
    properties: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    source_uri: str | None = None,
    expansion: str | None = None,
    content_hash: str | None = None,  # New parameter
) -> Node:
    ...
    # Use provided hash or compute
    computed_hash = content_hash or hashlib.sha256(content.encode()).hexdigest()
```

## Critical Files

- `src/context_service/services/context.py` - Main changes (store, assert_claim)

## Verification

1. **Unit test:** Add test that calls `assert_claim()` twice with same content, verify same node_id returned
2. **Static checks:** `just check` passes
3. **MCP test:** Use `context_store` tool to assert same claim twice, verify dedup works
