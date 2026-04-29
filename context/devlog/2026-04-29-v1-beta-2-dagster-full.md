# 2026-04-29: v1-β2 — Dagster pipeline (full)

## Summary

Shipped the complete Dagster pipeline: 6 assets, 3 schedules, 2 sensors, retry policies, poison queue, and resource wiring. The DAG implements Option B from `dag-architecture.md` — extraction and embedding run in parallel from `document_arrival_sensor`, custodian_visit waits on both, then custodian_finalize/fact_promotion/clustering follow with their own cadences.

Two review passes (Sonnet agents) caught 5 critical + 5 important + 3 low issues; all fixed before commit. Tests: 179 to 260 (+81). `just check` green.

## What landed

### Assets (6)

All partitioned by `silo_id` with `RetryPolicy(max_retries=3, delay=10.0, backoff=EXPONENTIAL)` and per-asset `dagster/concurrency_key` tags.

| Asset | Trigger | Cadence |
|-------|---------|---------|
| `extraction` | document_arrival_sensor | ~5 min batched |
| `embedding` | document_arrival_sensor | ~5 min parallel |
| `custodian_visit` | custodian_visit_schedule | `*/15 * * * *` |
| `custodian_finalize` | depends on custodian_visit | follows visit |
| `claim_to_fact_promotion` | fact_promotion_schedule | `0 * * * *` |
| `clustering` | clustering_schedule | `0 4 * * *` |

**DAG shape:** extraction and embedding have no inter-dependency and run concurrently from the same sensor. custodian_visit depends on both (waits for extraction claims AND embedding vectors before visiting clusters). custodian_finalize and fact_promotion both depend on custodian_visit. clustering depends on custodian_finalize and runs daily off-peak.

### Schedules (3)

- `custodian_visit_schedule` — `*/15 * * * *`, yields per-silo RunRequests by querying active silos from Memgraph.
- `fact_promotion_schedule` — `0 * * * *` (hourly), same per-silo pattern.
- `clustering_schedule` — `0 4 * * *` (daily 04:00 UTC), off-peak to avoid contention.

### Sensors (2)

- `document_arrival_sensor` — polls every 60s, triggers extraction+embedding when pending docs exist or staleness threshold (5 min) exceeded. Cursor state now JSON-encoded (review fix: hand-rolled `k=v,k=v` format was fragile for silo IDs containing `=` or `,`).
- `poison_queue_sensor` — fires on `DagsterRunStatus.FAILURE`, but only after retry count reaches 3 (review fix: was catching all failures including first-attempt transients). Writes run_id/step_key/error to Redis with 7-day TTL under `dagster:poison:{asset_key}:{run_id}`.

### Resources (5)

`MemgraphResource`, `QdrantResource`, `RedisResource`, `LLMResource`, `EmbeddingResource`. All implement `teardown_after_execution` with async close handling.

**Review fix:** `MemgraphResource.driver()` and `RedisResource.client()` were ignoring their own `uri`/`url` fields and pulling from global settings. Now use resource-configured values, making environment-level overrides work correctly.

### Review fixes

Two Sonnet agent passes identified issues; all fixed before commit:

**Critical (5):**
- `custodian_visit` now depends on both `extraction` AND `embedding` — DAG shape was broken (extraction only).
- `embedding.py` function renamed to `embedding_asset` — parameter/function name collision (`embedding: EmbeddingResource` shadowed the function).
- `clustering.py` closes `QdrantClient` in try/finally — was leaking on error path.
- Added `custodian_visit_schedule` — asset had no trigger and would never run.
- `document_arrival_sensor` now targets both `extraction` and `embedding` — was only triggering extraction.

**Important (4):**
- `fact_promotion.py` uses batched Cypher via `UNWIND` — was 1+2N RTTs (up to 1002 for N=500), now 3+P where P is promoted claims.
- `poison_queue_sensor` checks retry count — only poisons after retry 3.
- `custodian_finalize` counter only increments on successful promotion — was counting failures.
- Resource config bypass fixed (see above).

**Low (1):**
- `document_arrival_sensor` cursor encoding switched to JSON.

### Supporting changes

- `clustering/service.py`, `clustering/queries.py` — new Cypher for Dagster-compatible execution.
- `custodian/consensus_promotion.py`, `custodian/handlers/consensus.py` — adjusted for asset integration.
- `db/queries.py` — new batch queries for fact_promotion.
- `engine/qdrant_store.py`, `engine/queries.py` — close() methods and query additions.
- `extraction/service.py` — Dagster-compatible entry point.

### Tests added

- `test_extraction_asset.py` — output shape, zero-doc handling.
- `test_embedding_asset.py` — output shape, batch behavior.
- `test_custodian_visit_asset.py` — output shape, dependency check.
- `test_custodian_finalize_asset.py` — output shape, counter behavior.
- `test_clustering_asset.py` — output shape, dependency on custodian_finalize.
- `test_fact_promotion.py` — batched query behavior.
- `test_schedules.py` — all 3 schedules registered with correct crons.
- `test_dagster_resources.py` — resource config and teardown.
- `test_poison_queue.py` — TTL, push/pop, retry guard.
- `test_concurrency_tags.py` — all assets have tags and retry policies.
- `tests/integration/test_extraction_pipeline.py` — end-to-end (requires Docker stack).

## Counts

- **1 commit** (35 files, +2747/-220 lines).
- **Tests: 179 to 260** (+81 new tests).
- **`just check` green** — ruff + mypy strict pass.

## What's next

### Remaining v1-β phases

1. **β3 — SPLADE sparse retrieval.** Hybrid dense+sparse for better recall on entity names.
2. **β4 — silo portability.** Export/import, cross-silo federation prep.
3. **β5 — integration test pack.** Full Docker-based test suite for CI.
4. **β6 — paradigm completion + architecture cleanup.** EAG completion items + storage protocol adoption.

### Operational notes

- **First Dagster deploy** will need `dagster.yaml` concurrency pool config. Recommended: `extraction: 4`, `embedding: 4`, `custodian_visit: 2`, `clustering: 1`.
- **Poison queue dashboard** not yet built — items accumulate in Redis but no alerting/visibility surface.
- **Cost tracking** (`cost_usd` in asset outputs) returns 0.0 placeholder. Real billing integration deferred.

### Deferred to future

- R-003/R-005/R-006/R-007 batching findings from β0 review were superseded by this work — those code paths no longer exist or were rewritten.
- N-009 reconciliation worker (nodes without vectors) — still relevant, not yet scheduled.
