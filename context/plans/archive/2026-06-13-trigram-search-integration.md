# Trigram Text Search Integration

**Status:** Draft  
**Date:** 2026-06-13  
**Author:** Spec generated from codebase analysis

## Problem

The BM25 channel in `FusionRetriever` queries a Postgres `nodes` table that exists (migration `d441746be43d`) but is never written to. Data only goes to Memgraph. Result: BM25 channel always returns empty.

## Solution

Dual-write to Postgres on every node creation. Add pg_trgm index for fuzzy text matching alongside existing tsvector GIN index.

---

## 1. Schema Changes

### Current schema (from `d441746be43d`)

```sql
CREATE TABLE nodes (
    id UUID PRIMARY KEY,
    silo_id UUID NOT NULL,
    layer TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Existing indexes
CREATE INDEX ix_nodes_silo_id ON nodes (silo_id);
CREATE INDEX ix_nodes_layer ON nodes (layer);
CREATE INDEX ix_nodes_content_gin ON nodes USING GIN (to_tsvector('english', content));
```

### New migration: Add pg_trgm

```python
# alembic/versions/XXXX_add_trigram_index.py
revision = "XXXX"
down_revision = "42f64ba6df17"  # current head after merge

def upgrade() -> None:
    # Enable pg_trgm extension
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    
    # Add trigram GIN index
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_nodes_content_trgm
        ON nodes USING GIN (content gin_trgm_ops)
    """)
    
    # Add state column for supersession filtering
    op.add_column("nodes", sa.Column("state", sa.Text(), server_default="ACTIVE", nullable=False))
    op.create_index("ix_nodes_state", "nodes", ["state"])

def downgrade() -> None:
    op.drop_index("ix_nodes_state", table_name="nodes")
    op.drop_column("nodes", "state")
    op.execute("DROP INDEX IF EXISTS ix_nodes_content_trgm")
    # Don't drop extension (may be used elsewhere)
```

---

## 2. Write Path Changes

### Where to add dual-write

The write path flows:
```
MCP tools (remember.py, learn.py, etc.)
  -> context_store.py (_context_remember, _context_assert, etc.)
    -> sage/transactions.py (store_memory, store_claim, commit, etc.)
      -> Memgraph via HyperGraphStore.execute_write()
```

**Decision:** Add Postgres write in `sage/transactions.py` immediately after Memgraph write succeeds.

**Rationale:**
- Transactions.py is the canonical write point for all layers
- Keeps Postgres sync with Memgraph state transitions
- Avoids duplicating logic in each MCP tool

### Implementation

Add to `src/context_service/sage/transactions.py`:

```python
async def _sync_to_postgres(
    node_id: uuid.UUID,
    silo_id: str,
    layer: str,
    content: str,
    state: str = "ACTIVE",
) -> None:
    """Sync node to Postgres shadow table for text search.
    
    Best-effort: logs warning on failure, does not raise.
    Memgraph remains source of truth.
    """
    from context_service.telemetry.metrics import get_db_pool
    
    pool = get_db_pool()
    if pool is None:
        logger.warning("postgres_sync_skip_no_pool", node_id=str(node_id))
        return
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO nodes (id, silo_id, layer, content, state, created_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    state = EXCLUDED.state
                """,
                node_id, uuid.UUID(silo_id), layer, content, state
            )
    except Exception as exc:
        logger.warning(
            "postgres_sync_failed",
            node_id=str(node_id),
            silo_id=silo_id,
            error=str(exc),
        )
```

Call sites in transactions.py:
- `store_memory()` - after line 663 (after Memgraph write)
- `store_claim()` - after line 845 (after Memgraph write)
- `commit()` - after line 1242 (after Memgraph write)
- `accept_proposal()` - after line 1524 (when creating Belief)

### Supersession handling

In `_create_supersedes_edge()` (line 2007), add:

```python
# After setting loser state to SUPERSEDED:
await _sync_to_postgres(
    node_id=uuid.UUID(loser_id),
    silo_id=silo_id,
    layer="",  # layer doesn't change
    content="",  # content doesn't change
    state=NodeState.SUPERSEDED.value,
)
```

Alternative: Use UPSERT with state-only update when content is empty.

---

## 3. Query Changes

### Current BM25 channel (fusion.py lines 339-411)

Uses `ts_rank` with `plainto_tsquery` for full-text search.

### Enhanced hybrid approach

Replace with trigram + tsvector hybrid scoring:

```python
async def _bm25_channel(
    self,
    query: str,
    scope: ScopeContext,
    top_k: int,
    layers: list[str] | None,
) -> ChannelResult:
    """Hybrid BM25 + trigram text search via Postgres."""
    if not query.strip():
        return ChannelResult(channel_name="bm25", ranked_ids=[], latency_ms=0.0)

    pool = get_db_pool()
    if pool is None:
        return ChannelResult(
            channel_name="bm25",
            ranked_ids=[],
            latency_ms=0.0,
            error="pg_pool unavailable",
        )

    t0 = time.perf_counter()
    try:
        silo_id = str(scope.silo_id)
        
        # Hybrid: combine ts_rank (BM25-like) with trigram similarity
        # Weight: 0.7 ts_rank + 0.3 trigram (tunable)
        if layers:
            sql = """
                SELECT id,
                       (0.7 * COALESCE(ts_rank(to_tsvector('english', content),
                                              plainto_tsquery('english', $1)), 0)
                        + 0.3 * COALESCE(similarity(content, $1), 0)) AS rank
                FROM nodes
                WHERE silo_id = $2
                  AND state = 'ACTIVE'
                  AND layer = ANY($3)
                  AND (
                      to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                      OR similarity(content, $1) > 0.1
                  )
                ORDER BY rank DESC
                LIMIT $4
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, query, silo_id, layers, top_k)
        else:
            sql = """
                SELECT id,
                       (0.7 * COALESCE(ts_rank(to_tsvector('english', content),
                                              plainto_tsquery('english', $1)), 0)
                        + 0.3 * COALESCE(similarity(content, $1), 0)) AS rank
                FROM nodes
                WHERE silo_id = $2
                  AND state = 'ACTIVE'
                  AND (
                      to_tsvector('english', content) @@ plainto_tsquery('english', $1)
                      OR similarity(content, $1) > 0.1
                  )
                ORDER BY rank DESC
                LIMIT $3
            """
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, query, silo_id, top_k)

        ranked_ids = [str(row["id"]) for row in rows]
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="bm25",
            ranked_ids=ranked_ids,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - t0) * 1000.0
        return ChannelResult(
            channel_name="bm25",
            ranked_ids=[],
            latency_ms=latency_ms,
            error=str(exc),
        )
```

### Why hybrid?

| Approach | Pros | Cons |
|----------|------|------|
| tsvector only | Good for stemmed English | Misses typos, partial matches |
| trigram only | Fuzzy matching, typo-tolerant | No semantic awareness |
| Hybrid | Best of both | Slightly more compute |

Trigram catches: "usre" -> "user", partial prefixes, non-English terms.

---

## 4. Transaction Semantics

### Failure modes

| Scenario | Behavior |
|----------|----------|
| Memgraph succeeds, Postgres fails | Log warning, continue. Memgraph is source of truth. |
| Memgraph fails | Raise exception, no Postgres write attempted. |
| Postgres write slow (>100ms) | Consider async fire-and-forget in future. |

### Consistency model

- **Eventually consistent**: Postgres may lag Memgraph briefly on failure
- **Self-healing**: On next write to same node (supersession), state syncs
- **No distributed transaction**: Complexity not justified for read-replica use case

### Future consideration: Async write

For p95 latency improvement, could use background task:

```python
# Not implemented in v1, but noted for future
asyncio.create_task(_sync_to_postgres(...))
```

Risk: fire-and-forget failures harder to observe. Start with sync, measure, optimize.

---

## 5. Migration Strategy

### Backfill existing data

One-time script to populate Postgres from Memgraph:

```python
# scripts/backfill_postgres_nodes.py
async def backfill():
    """Backfill Postgres nodes table from Memgraph."""
    pool = get_db_pool()
    store = get_graph_store()
    
    # Fetch all nodes from Memgraph
    cypher = """
    MATCH (n:Node)
    WHERE n.content IS NOT NULL
    RETURN n.id AS id, n.silo_id AS silo_id, 
           n.properties.layer AS layer, n.content AS content,
           COALESCE(n.properties.state, 'ACTIVE') AS state
    """
    rows = await store.execute_query(cypher, {})
    
    # Batch insert to Postgres
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO nodes (id, silo_id, layer, content, state, created_at)
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (id) DO NOTHING
            """,
            [(r["id"], r["silo_id"], r["layer"], r["content"], r["state"]) for r in rows]
        )
```

Run after deploying migration, before enabling BM25 channel.

---

## 6. Performance Considerations

### Index sizes (estimates)

| Index | Size estimate (1M nodes, 500 char avg) |
|-------|---------------------------------------|
| ix_nodes_content_gin (tsvector) | ~200MB |
| ix_nodes_content_trgm (trigram) | ~400MB |
| Total additional | ~600MB |

### Query performance

- Target: <50ms p95 for top-k=20
- GIN indexes support concurrent reads during writes
- `similarity()` threshold (0.1) prevents full scans

### Write overhead

- Memgraph write: ~50ms p95 (existing)
- Postgres sync: ~5-10ms additional
- Acceptable given recall target of <300ms

---

## 7. Tasks

1. [ ] Create migration `XXXX_add_trigram_index.py`
2. [ ] Add `_sync_to_postgres()` helper to transactions.py
3. [ ] Call sync from `store_memory()`, `store_claim()`, `commit()`, `accept_proposal()`
4. [ ] Update supersession to sync state changes
5. [ ] Update `_bm25_channel()` with hybrid scoring
6. [ ] Write backfill script
7. [ ] Add metrics: `postgres_sync_latency_ms`, `postgres_sync_errors_total`
8. [ ] Test: verify BM25 channel returns results after dual-write

---

## 8. Open Questions

1. **Hybrid weights**: 0.7/0.3 tsvector/trigram is a starting guess. Tune based on recall@k metrics.
2. **Trigram threshold**: 0.1 is permissive. May need to raise if too many false positives.
3. **Backfill timing**: Run before or after switching to dual-write? (After migration, before traffic)
