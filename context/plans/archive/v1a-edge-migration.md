# Plan: Edge Migration — `BELONGS_TO` → `MEMBER_OF`

**Status:** Approved 2026-04-28
**Branch:** `phase-eag-b-edge-migration`
**Workstream:** v1-α (close paradigm gaps)

## Goal

Migrate legacy `BELONGS_TO` edges to `MEMBER_OF` in live silos and drop the dual-read pattern from all queries. Close two outdated TODOs in `eag-integration-audit.md`.

## Current state (anchored from audit on 2026-04-28)

- No active write emits `BELONGS_TO`. Every `CREATE`/`MERGE` on the cluster-membership edge already writes `MEMBER_OF` (e.g. `db/queries.py:107` `CREATE_MEMBER_OF`, `db/queries.py:189` `BATCH_CREATE_MEMBER_OF`).
- Reads carry a `[r:BELONGS_TO|MEMBER_OF]` dual-pattern as a fallback for legacy data:
  - `db/queries.py:123, 129, 321, 389`
  - `db/custodian_queries.py:371`
  - `db/custodian_read_queries.py:35, 51, 119, 120, 160`
- `CITEEdgeType.REFERENCES` already exists in `primitives/src/primitives/schema/edges.py:25`. The audit's claim that `EDGE_REFERENCES` is "not in `CITEEdgeType`" was stale.

## Tasks (priority order)

1. **One-shot Cypher migration script `scripts/migrate_belongs_to.py`.**
   ```cypher
   MATCH (n)-[r:BELONGS_TO]->(c:Cluster {silo_id: $silo_id})
   MERGE (n)-[r2:MEMBER_OF]->(c)
     ON CREATE SET r2.weight = r.weight,
                   r2.created_at = r.created_at,
                   r2.migrated_from = 'BELONGS_TO'
   DELETE r
   ```
   - CLI: `uv run python -m scripts.migrate_belongs_to --silo-id <id>` and `--all-silos`.
   - Idempotent. Logs counts: migrated, already on MEMBER_OF, skipped.

2. **`--verify` flag on the same script.**
   - Runs `MATCH ()-[r:BELONGS_TO]->() RETURN count(r)`. Non-zero => fail.

3. **Drop the dual-read pattern.** Mechanical search/replace `[r:BELONGS_TO|MEMBER_OF]` → `[r:MEMBER_OF]` in:
   - `db/queries.py:123, 129, 321, 389`
   - `db/custodian_queries.py:371`
   - `db/custodian_read_queries.py:35, 51, 119, 120, 160`

4. **Lint guard against regressions.**
   - `tests/test_no_belongs_to_writes.py`: greps `src/` for `(MERGE|CREATE).*BELONGS_TO`. Fails if any match.

5. **Close audit doc TODOs.**
   - `eag-integration-audit.md`: remove TODO #2 (`BELONGS_TO`/`PART_OF` inconsistency). `PART_OF` is intentionally separate (inter-cluster hierarchy), not the same relationship.
   - `eag-integration-audit.md`: remove TODO #1 (`EDGE_REFERENCES` gap). `CITEEdgeType.REFERENCES` exists.

## Out of scope

- `PART_OF` edges (inter-cluster hierarchy, intentionally separate).
- Any change to `CITEEdgeType` in primitives.
- Migration on dev/test instances with no real `BELONGS_TO` data.

## Done criteria

- Script exists, idempotent, dry-run against local docker stack with seeded `BELONGS_TO` data succeeds.
- All read queries use `[r:MEMBER_OF]` (no dual-pattern).
- Lint test for `BELONGS_TO` writes passes.
- Two TODO items closed in `eag-integration-audit.md`.
- `just check` and `just test` pass.
