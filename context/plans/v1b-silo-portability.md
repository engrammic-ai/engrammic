# Plan: Silo Export / Import Migration Tooling

**Status:** Draft 2026-04-28
**Branch:** `phase-migration-silo-portability`
**Workstream:** v1-β phase 4

## Goal

Make silos portable. Provide CLI scripts to export a silo's full graph state to JSONL and import it into another environment. Generalize the one-shot pattern from `scripts/migrate_belongs_to.py`.

## Why

Knowzilla and Silt onboarding (per the v1 wiki page) needs a way to ship a silo from one environment to another — moving prototype data into prod, cloning prod silos into staging for debugging, exporting on customer offboarding. No tooling for this exists today.

## Current state (anchored from audit on 2026-04-28)

- `scripts/migrate_belongs_to.py` is the only migration script — narrow, edge-type-specific.
- `scripts/__init__.py` exists; pytest pythonpath wired (PR #5).
- `services/silo.py` exposes silo CRUD (`SiloService`).
- No general node/edge dump format. No schema versioning for graph data.
- Qdrant vectors are derivable from content + the embedding service, so they don't need to be in the dump by default.

## Tasks (priority order)

1. **Define the export format.** `architecture/silo-portability.md`. Versioned (`schema_version: 1`). Forward-compat: unknown fields preserved on round-trip. Format:
   ```jsonl
   {"_manifest": {"schema_version": 1, "silo_id": "...", "exported_at": "...", "source_env": "..."}}
   {"kind": "node", "id": "...", "labels": ["Claim", "Fact"], "properties": {...}}
   {"kind": "edge", "src": "...", "dst": "...", "type": "REFERENCES", "properties": {...}}
   ```
   First line is always the manifest. One node or edge per subsequent line.

2. **Export script** (`scripts/silo_export.py`).
   - CLI: `--silo-id <id> --out <path>`, optional `--include-vectors` (default false).
   - Streams node and edge dumps from Memgraph; writes to JSONL on stdout or file. Streaming is critical — silos can be large.
   - Cypher: `MATCH (n {silo_id: $silo_id}) RETURN labels(n) AS labels, properties(n) AS props` (paginated by id range or LIMIT/OFFSET).
   - Edges: `MATCH (a {silo_id: $silo_id})-[r]->(b {silo_id: $silo_id}) RETURN a.id, b.id, type(r), properties(r)`. (Edges across silo boundaries are a violation; if encountered, log and skip.)
   - With `--include-vectors`: also emit `{"kind": "vector", "node_id": "...", "dense": [...], "sparse": {...}}` entries from Qdrant.

3. **Import script** (`scripts/silo_import.py`).
   - CLI: `--in <path> --target-silo <id>`, optional `--rename-silo <new_id>` for cloning, `--dry-run`.
   - Validates the manifest: schema version, target silo doesn't already exist (unless `--force`).
   - Streams the JSONL line-by-line. For nodes: `MERGE (n {id: $id, silo_id: $silo_id}) SET n += $props, n :Label1 :Label2 ...` (multi-label set). For edges: `MATCH (a {id: $src}), (b {id: $dst}) MERGE (a)-[r:TYPE]->(b) SET r += $props`.
   - Idempotent: re-running on a target with partial data completes the import without duplication.
   - Vector restoration: if the export includes vectors, upsert to Qdrant. Otherwise (default), the importer warns and recommends running the embedding pipeline + SPLADE backfill.

4. **Cross-environment safety guards.**
   - `--rename-silo` is required when target environment already has a silo with the same ID (prevents accidental overwrite).
   - The manifest's `source_env` is logged on import; warn if importing prod data into a non-prod environment without `--allow-cross-env`.

5. **Round-trip test.** `tests/integration/test_silo_portability.py`.
   - Seed a silo with ~20 nodes + ~30 edges + a few hierarchies.
   - Export → import to a fresh silo with `--rename-silo`.
   - Assert node count, edge count, label sets match.
   - Run `context_query` on both silos with the same query; assert ranked results overlap by ≥ 90% (some drift acceptable due to vector regen, none if `--include-vectors`).

6. **Docs update.** Add a "Silo portability" section to `architecture/README.md` cross-linking to the schema doc.

## Out of scope

- Cross-version schema migration on import (v1 import only handles `schema_version: 1` exports; defer migration logic until v2 schema exists).
- Encrypted exports (defer to v1.0 with proper KMS integration).
- Incremental / delta export (always full snapshot).
- Compression (operators can `gzip` the JSONL externally if needed).
- Import into a non-empty silo (always a fresh target unless `--force`).

## Done criteria

- Export script produces a complete JSONL dump of any silo, with manifest header.
- Import script reproduces the silo in another environment, idempotent, with optional rename.
- Round-trip integration test green.
- `architecture/silo-portability.md` documents the schema and CLI usage.
- `just check` + `just test` green.
