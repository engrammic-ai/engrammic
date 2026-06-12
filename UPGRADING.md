# Upgrading

## Running migrations

All schema changes are managed by Alembic. After pulling a new release, run:

```bash
just db-migrate
```

or directly:

```bash
uv run alembic upgrade head
```

This is safe to run on every update — it is a no-op when already at head.

## Migration history

| Revision | Description |
|----------|-------------|
| 0001–0015 | Initial schema through license table |
| 0016 | Reasoning chain steps fields (tx7) |
| d441746be43d | BM25 shadow table (`nodes`) with GIN index — required for full-text recall |
| 42f64ba6df17 | Merge head: unifies the `0016` and `d441746be43d` branches |

### About the merge migration (42f64ba6df17)

This migration has two parents: `0016` and `d441746be43d`. Alembic requires both
to be applied before it can stamp `42f64ba6df17` as head. `alembic upgrade head`
handles this automatically regardless of which branch you were on.

If you see `Multiple head revisions are present` when running alembic commands,
run `alembic upgrade head` once to resolve it.

### Users upgrading from before d441746be43d

The `d441746be43d` migration creates a `nodes` Postgres table used by the BM25
retrieval channel. This table is populated on write (remember/learn), so existing
nodes stored only in Memgraph will not appear in BM25 results until they are
re-written. Semantic and graph-based recall are unaffected.

### Downgrade note

Downgrading past `42f64ba6df17` requires targeting a specific revision:

```bash
uv run alembic downgrade 0016       # revert only the GIN index branch
uv run alembic downgrade d441746be43d  # revert only the tx7 branch
```

Downgrading `d441746be43d` drops the `nodes` table and all BM25 index data.
