# Plan: Dagster Asset Migration (the spine of v1-β)

**Status:** Draft 2026-04-28
**Branches:** `phase-dagster-a-resources-extraction`, `phase-dagster-b-embedding-custodian`, `phase-dagster-c-clustering-scheduling`
**Workstream:** v1-β phase 2 (sub-phased a/b/c)

## Goal

Move the extraction → embedding → custodian → clustering → fact-promotion pipeline from ad-hoc service calls to Dagster assets, partitioned by `silo_id`, with retries, observability, and scheduling. The DAG shape follows `docs/dag-architecture.md` Option B: parallel embed + extract, both downstream of doc ingestion.

## Why

`pipelines/assets/` today contains exactly one asset (`fact_promotion.py`, unscheduled). Every pipeline step still runs as a service-call sequence with no retry budget, no per-silo isolation, no run history, and no observable metrics. Production reliability needs Dagster on the spine.

## Cadence by asset (NOT triggered per-document)

The arrows between assets are **data dependencies**, not trigger-time coupling. Each asset runs at its own cadence; downstream waits for upstream's data to exist, not for upstream to run.

| Asset | Trigger | Realistic cadence |
|---|---|---|
| Extraction | Sensor on `:Document` arrival | Batched per silo: every ~5 min or when N docs queued |
| Embedding | Sensor on pending-vector count | Same window as extraction; runs in parallel |
| Custodian visit | Schedule | Every 15 min per active silo |
| Custodian finalize | Schedule (post-visit) | Same window as visit |
| Fact-promotion sweep | Schedule | Hourly per silo |
| Clustering | Schedule | Daily off-peak per silo (Leiden is expensive) |

So a single doc ingested doesn't fire clustering — clustering runs once a day on accumulated state. A burst of 50 docs gets one extraction batch, one embedding batch, one or two visits, and clustering catches up overnight.

Concurrency: across silos parallel via per-silo concurrency keys; within a silo, single-runner per partition but each run batches (Memgraph supports concurrent writes; LLM calls bounded by a semaphore).

The DAG handles bulk + scheduled processing only. **Real-time per-call writes** via MCP tools (`context_remember`, `context_assert`, `context_commit`, `context_reflect`) bypass Dagster entirely — they go through `services/context.py::store()` synchronously. The DAG is for scaled bulk ingest, custodian sweeps, and periodic clustering.

## Current state (anchored from audit on 2026-04-28)

- `src/context_service/pipelines/definitions.py` — bare `Definitions` with `all_assets`, no jobs/schedules, plus `all_sensors`. Loads cleanly via `just dagster-web`.
- `src/context_service/pipelines/resources.py` — has `MemgraphResource` (ConfigurableResource pattern), uses `_close_async` helper for teardown across event loops. Pattern is sound; need to extend with Qdrant/Redis/LLM/Embedding resources.
- `src/context_service/pipelines/assets/__init__.py` exports `claim_to_fact_promotion` only.
- `src/context_service/pipelines/sensors/` — exists with `all_sensors` export. Confirm what's there at kickoff.
- Existing services to migrate:
  - `extraction/service.py` (filter chain: rules → wikidata → llm_classifier → orchestrator)
  - `embeddings/` (Jina, Vertex; protocol in `base.py`)
  - `custodian/visit.py` + `custodian/dispatch.py` (the visit loop)
  - `custodian/consensus_promotion.py` (R2 → :Finding)
  - `clustering/service.py` (Leiden + hierarchical summaries)

## Phase β2a — Resources + extraction asset

**Branch:** `phase-dagster-a-resources-extraction`
**Team shape:** 2 agents (resources + extraction in parallel)

### Tasks

1. **Finalize `pipelines/resources.py`.** Extend with `QdrantResource`, `RedisResource`, `LLMResource` (anthropic/gemini/openai dispatch via existing `llm/base.py` protocol), `EmbeddingResource` (jina/vertex via `embeddings/base.py`). Match the `MemgraphResource` pattern. Each resource exposes a typed driver/client per asset run; teardown via `_close_async`.

2. **Extraction asset** (`pipelines/assets/extraction.py`). Partitioned by `silo_id` via `DynamicPartitionsDefinition`. Reads pending `:Document` nodes (Cypher: `MATCH (d:Document {silo_id: $silo_id}) WHERE NOT EXISTS((d)-[:EXTRACTED_FROM]->(:Claim)) RETURN d LIMIT $batch`), runs `extraction.service.extract` over each, writes `:Claim` + `:ProposedEdge` nodes. Emits Dagster `Output` with `metadata={"docs_processed", "claims_created", "tokens_used", "cost_usd", "duration_s"}`.

3. **Document arrival sensor** (`pipelines/sensors/document_arrival.py`). Polls per silo; if pending docs > threshold or last extraction > 5min ago, triggers the partition.

4. **Tests.** `tests/test_extraction_asset.py` (unit) — mock the resources, assert the asset emits the right Output shape. `tests/integration/test_extraction_pipeline.py` — seed two docs, run the asset, verify claims land.

### Done criteria

- Resources for memgraph/qdrant/redis/llm/embedding all defined and used by at least one asset.
- Extraction asset visible in `just dagster-web`; manual partition launch produces claims.
- Sensor triggers on new documents.

## Phase β2b — Embedding + custodian assets

**Branch:** `phase-dagster-b-embedding-custodian`
**Team shape:** 2 agents (embedding + custodian visit in parallel)

### Tasks

1. **Embedding asset** (`pipelines/assets/embedding.py`). Partitioned by `silo_id`, **parallel** with extraction (Option B). Reads pending nodes without Qdrant vectors, batches via `EmbeddingService.embed_batch`, upserts to Qdrant. Same Output metadata shape.

2. **Custodian visit asset** (`pipelines/assets/custodian_visit.py`). Partitioned by `silo_id`. Runs the visit loop from `custodian/visit.py`, writes `:Claim:Commitment` nodes carrying R1 evidence. Reads cluster heat/freshness/priority from `signals/`. Emits visit metrics (visits, commitments_created, llm_calls, cost).

3. **Custodian finalize asset** (`pipelines/assets/custodian_finalize.py`). Runs `custodian.consensus_promotion.promote_with_consensus` for clusters that have hit R2 thresholds. Produces `:Finding` from `:Claim:Commitment` aggregates.

4. **Asset graph wiring**: extraction + embedding both have no graph dependency on each other (parallel); custodian visit depends on extraction (needs `:Claim` nodes); custodian finalize depends on custodian visit.

5. **Tests** for each asset (unit + integration as in β2a).

### Done criteria

- Embedding runs in parallel with extraction, no inter-asset blocking.
- Custodian visit produces `:Claim:Commitment` nodes from extracted claims.
- Custodian finalize produces `:Finding` from R2 consensus.
- Each asset emits structured metrics with cost tracking.

## Phase β2c — Clustering + fact-promotion sweep + scheduling

**Branch:** `phase-dagster-c-clustering-scheduling`
**Team shape:** 2 agents (clustering + scheduling/sensors in parallel)

### Tasks

1. **Clustering asset** (`pipelines/assets/clustering.py`). Partitioned by `silo_id`. Runs Leiden via `clustering/service.py`, produces `:Cluster` nodes + `:MEMBER_OF` edges + hierarchical summaries. Depends on custodian finalize (needs settled `:Finding` nodes for cluster summaries).

2. **Wire `claim_to_fact_promotion` into the asset graph.** It currently exists standalone. Add an `ins` declaration so it depends on custodian visit (needs `:Claim` nodes with evidence). Add a `ScheduleDefinition` (hourly per active silo).

3. **Schedules + Sensors.**
   - `ScheduleDefinition` for clustering (daily per silo, off-peak).
   - `ScheduleDefinition` for fact-promotion sweep (hourly per silo).
   - `SensorDefinition` for document arrival (already in β2a).
   - `RunStatusSensorDefinition` for poison-queue handling: failed runs that exhaust retries land in a Redis-backed poison queue with TTL (e.g. 7 days).

4. **Update `docs/dag-architecture.md`** to reflect the actually-shipped DAG. Replace any "Option A vs Option B" hedging with the concrete chosen shape.

5. **Concurrency keys.** Per-silo concurrency limits via Dagster's `tags={"dagster/concurrency_key": silo_id}` so a single noisy silo doesn't starve others. Global LLM concurrency cap to respect provider rate limits.

6. **Retry budgets.** Per-asset `RetryPolicy` with exponential backoff; max 3 retries; permanent failures route to poison queue.

### Done criteria

- Full asset graph visible in `just dagster-web`; executes end-to-end on a seeded silo.
- All assets scheduled or sensor-triggered.
- Per-silo concurrency limits enforced; LLM rate limits respected.
- Poison queue captures permanent failures.
- `docs/dag-architecture.md` updated.

## Cross-cutting (β2 overall)

### Done criteria

- A new document ingested into a silo flows through extraction → embedding → custodian visit → finalize → clustering → fact-promotion without manual intervention.
- Each asset emits structured metrics (rows processed, errors, duration, cost in USD).
- Failed runs retry with backoff; permanent failures land in a poison queue.
- Integration test (β5) passes for the e2e flow.
- `just check` + `just test` green; `just dagster-web` boots cleanly.

### Out of scope

- Real-time streaming ingest (still batch-pull via sensors).
- Cost-aware scheduling (just rate limits via concurrency keys; no spend budgeting).
- Cross-silo reconciliation jobs.
- UI for manual asset launches beyond what `just dagster-web` provides natively.

## Findings to absorb (from review 2026-04-28)

The 2026-04-28 codebase review (`context/review/codebase-review-2026-04-28.md`) flagged four batching findings that belong in the asset migrations:

- **R-003** / **F-016** (β2a — extraction asset) — `apply_claims_to_graph` and `apply_document_claims` issue 3-4 `execute_write` calls per triple (~100 RTTs per extraction job). When the extraction asset is rewritten, collapse to UNWIND-batched queries (one upsert claims + one upsert mentions + one attach passages + one attach references; four total instead of N×4).
- **R-005** (β2b — custodian finalize asset) — `consensus_promotion.py:46-51` issues per-chain `CREATE_PROMOTED_FROM_EDGE` calls. Batch via UNWIND in the asset rewrite.
- **R-006** (β2c — clustering asset) — `clustering/service.py:164-177` writes hierarchy per-cluster. Batch.
- **R-007** (β2c — clustering asset) — `clustering/service.py:383-399` upserts Qdrant cluster embeddings one-by-one despite the batch upsert API. Use the batch endpoint.
- **R-004** (already absorbed) — `clustering/service.py:372` unpacked `embed()` as a tuple. Fixed in `phase-eag-c-review-cleanup` commit `86baa4c`. No β2 work needed.

These four are not gating; the existing service-layer code paths still work, just inefficiently. The asset rewrites are the natural place to fix them.
