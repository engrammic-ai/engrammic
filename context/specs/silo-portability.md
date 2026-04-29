# Silo Portability: Export/Import Format

**Schema version:** 1
**Status:** Stable (v1-beta4)

## Purpose

Defines the JSONL wire format for transferring a silo's full graph state between
context-service environments. Use cases: prototype-to-prod promotion, staging
snapshots for debugging, customer offboarding.

## Format

A portability dump is a plain JSONL file (UTF-8, LF line endings). Line order
within a section does not matter. The file is divided into two logical sections:

1. **Manifest** — always the first line.
2. **Records** — one node, edge, or vector per line.

### Manifest line

```json
{
  "_manifest": {
    "schema_version": 1,
    "silo_id": "3f4a82c0-...",
    "exported_at": "2026-04-29T12:00:00Z",
    "source_env": "production"
  }
}
```

Fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `schema_version` | int | yes | Always `1` for this revision. Importer rejects unknown versions. |
| `silo_id` | string (UUID) | yes | The silo as it existed in the source environment. |
| `exported_at` | string (ISO 8601) | yes | UTC timestamp of the export run. |
| `source_env` | string | yes | Value of `ENVIRONMENT` setting at export time. |

### Node record

```json
{
  "kind": "node",
  "id": "abc123",
  "labels": ["Claim", "Fact"],
  "properties": {
    "silo_id": "3f4a82c0-...",
    "content": "...",
    "created_at": "2026-04-10T08:00:00Z"
  }
}
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `kind` | `"node"` | Discriminator. |
| `id` | string | Memgraph internal element ID (opaque; used to match edge endpoints). |
| `labels` | string[] | All Cypher labels on the node, e.g. `["Claim", "Fact"]`. |
| `properties` | object | All node properties. `silo_id` will be rewritten to the target silo on import if `--rename-silo` is given. |

### Edge record

```json
{
  "kind": "edge",
  "src": "abc123",
  "dst": "def456",
  "type": "REFERENCES",
  "properties": {
    "weight": 0.87,
    "created_at": "2026-04-10T08:01:00Z"
  }
}
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `kind` | `"edge"` | Discriminator. |
| `src` | string | Element ID of the source node (matches a `node` record's `id`). |
| `dst` | string | Element ID of the destination node. |
| `type` | string | Relationship type, e.g. `"REFERENCES"`. |
| `properties` | object | All edge properties. |

Edges whose `src` or `dst` node does not belong to the silo are a schema
violation. The exporter logs and skips them.

### Vector record (optional)

Present only when the export was produced with `--include-vectors`.

```json
{
  "kind": "vector",
  "node_id": "abc123",
  "dense": [0.12, -0.34, ...]
}
```

Fields:

| Field | Type | Notes |
|---|---|---|
| `kind` | `"vector"` | Discriminator. |
| `node_id` | string | The `properties.id` of the corresponding node record (not the element ID). |
| `dense` | float[] | Dense embedding vector (Jina / Vertex dimensions). |

## Versioning and forward compatibility

Unknown top-level keys in any record are preserved on round-trip. Importers
MUST reject `schema_version` values greater than their highest supported
version (currently 1). Future versions increment `schema_version` and document
migration rules in this file.

## CLI reference

### Export

```bash
uv run python -m scripts.silo_export \
    --silo-id <uuid> \
    --out dump.jsonl \
    [--include-vectors] \
    [--page-size 500]
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--silo-id` | required | UUID of the silo to export. |
| `--out` | required | Output path for the JSONL file. |
| `--include-vectors` | off | Also export dense vectors from Qdrant. |
| `--page-size` | 500 | Nodes per Cypher batch (reduce for large silos). |

### Import

```bash
uv run python -m scripts.silo_import \
    --in dump.jsonl \
    --target-silo <uuid> \
    [--rename-silo <new-uuid>] \
    [--dry-run] \
    [--force] \
    [--allow-cross-env]
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--in` | required | Path to JSONL dump. |
| `--target-silo` | required | UUID of the target silo (must already exist in Memgraph unless `--force`). |
| `--rename-silo` | off | Rewrite `silo_id` on all records to this value. Required when source and target environments share a silo ID. |
| `--dry-run` | off | Parse and validate without mutating. |
| `--force` | off | Skip the pre-existing-silo guard. |
| `--allow-cross-env` | off | Suppress the cross-environment warning. |

## Safety rules

1. `--rename-silo` is required when the target environment already has a silo
   with the same ID as the source (prevents silent overwrites).
2. The manifest's `source_env` is logged on every import. A warning is emitted
   when importing from a different environment (e.g. `production` into
   `development`) unless `--allow-cross-env` is passed.
3. Import is idempotent: re-running on a partially-imported target completes
   the import without duplicating nodes or edges (`MERGE` semantics throughout).
4. Vectors are optional. If the dump has no vector records, the importer warns
   and recommends running the embedding pipeline to regenerate them.
