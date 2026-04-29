# v1-β Master Plan

**Status:** Draft 2026-04-28
**Track scope:** production hardening + paradigm completion. UI (admin REST/dashboard) and billing are explicitly deferred to v1.0+.
**Track question:** does the engine work correctly under production conditions, and are silos portable enough for design-partner onboarding?

This is an index. Each phase below gets a detailed sub-plan in `context/plans/v1b-*.md` at phase kick-off (same pattern as v1-α). Sub-plans are deferred to kick-off rather than written all at once because earlier phases inform the later ones (e.g. how silo ownership is enforced shapes how the Dagster assets thread `auth_ctx`).

## Why

After v1-α the paradigm contracts have implementations, but the production surface is thin:

- `pipelines/assets/` has exactly one asset (`fact_promotion.py`, unscheduled). The whole extraction → embedding → custodian → clustering pipeline still runs as ad-hoc service calls, not as Dagster assets with partitions, retries, and observability.
- Hybrid retrieval is half-built: dense via Qdrant works; SPLADE sparse channel referenced in plans, never wired.
- Auth resolves at session start in MCP (per-request transport headers deferred from v1-α). `silo.org_id == auth_ctx.org_id` is not yet enforced anywhere.
- Silos can't be exported or imported. Knowzilla and Silt onboarding will need this.
- Integration coverage is thin — a handful of tests, no end-to-end ingest → query flow.

v1-β closes those gaps. Nothing fancy, nothing speculative.

## Out of scope

- REST admin / dashboard surface (UI)
- Basic billing / metering
- On-prem deployment, multi-region, advanced RBAC, public SDK, polished UX, OSS release (carry-over from v1 wiki)

## Phase map

```
β1 Auth completion + Silo ownership   ──►  unblocks β2, β3, β4 properly
β2 Dagster asset migration            ──►  β2a → β2b → β2c (sequential)
β3 SPLADE hybrid retrieval            ──►  parallel with β2 (no overlap)
β4 Migration tooling                  ──►  parallel with β2 (no overlap)
β5 Integration test pack              ──►  runs alongside β2 as each asset lands
β6 Paradigm completion + hygiene      ──►  opportunistic; pick off as time allows
```

Suggested kickoff order: **β1 → (β2a + β3 + β4) in parallel → β2b → β2c → β6**. β5 weaves through β2.

---

## Phase β1: Auth completion + Silo ownership

**Branch:** `phase-eag-d-auth-finish`
**Sub-plan:** `v1b-auth-finish.md` (TBD at kickoff)
**Team shape:** 1 agent (small, sequential)

### Goal

Finish the auth surface from v1-α and add the silo-ownership enforcement that v1-α explicitly deferred.

### Tasks

1. **Per-request MCP auth.** Replace the `MCP_DEV_TOKEN` env-var stop-gap in `auth/resolve.py`. Investigate FastMCP's `Context` parameter (or session metadata) for per-request transport headers. If FastMCP doesn't expose request-scoped auth in a stable way, document the limitation precisely and keep the env-var path for dev only — but make sure prod paths fail closed (already done in v1-α).
2. **Silo ownership enforcement.** Every read and write tool that takes `silo_id` must check `silo.org_id == auth_ctx.org_id` and raise on mismatch. Add a single helper `services/silo.py::assert_silo_belongs_to_org(silo_id, auth_ctx)` and call it from every MCP tool entry point + REST endpoint (currently just `/health`, but the helper is forward-looking). Cache the org → silo map in Redis (already wired) to avoid an extra DB round-trip per call.
3. **Verify WorkOS SDK method.** Phase 4 left a TODO — `workos_client.verify_session` calls `authenticate_with_session_token`; this hasn't been validated against a real tenant. Either confirm the API or refactor to whatever the modern SDK exposes.

### Done criteria

- MCP tool calls under `AUTH_ENABLED=true` resolve auth per-request, not at session start.
- Cross-org silo access raises 403 (or equivalent MCP error). Regression test pinned.
- WorkOS verify call works against a real tenant or the API is documented as-is with a verified-against version.
- `just check` and `just test` green.

### Out of scope

- Role-based access within an org (RBAC is v1.0+).
- Audit logging of auth decisions.

---

## Phase β2: Dagster asset migration

**Branches:** `phase-dagster-a-resources`, `phase-dagster-b-embedding-custodian`, `phase-dagster-c-clustering-promotion`
**Sub-plans:** `v1b-dagster-a.md`, `v1b-dagster-b.md`, `v1b-dagster-c.md`
**Team shape per sub-phase:** 2-3 agents in parallel (one per asset family + one for tests)

This is the spine of v1-β. The DAG shape is documented in `docs/dag-architecture.md` (Option B: parallel embed + extract, partitioned by `silo_id`).

### β2a: Resources + extraction asset

- **Resources** (`pipelines/resources.py`): finalize `MemgraphResource`, `QdrantResource`, `RedisResource`, `LLMResource`, `EmbeddingResource`. Each exposes a typed driver/client per asset run.
- **Extraction asset** (`pipelines/assets/extraction.py`): partitioned by `silo_id`. Reads pending `:Document` nodes, runs the extraction filter chain (rules → wikidata → llm_classifier → orchestrator), writes `:Claim` + `:ProposedEdge` nodes. Emits Dagster Output with run metrics.
- **Sensor**: detects new docs in a silo and triggers the extraction partition.

### β2b: Embedding + custodian assets

- **Embedding asset** (`pipelines/assets/embedding.py`): partitioned by `silo_id`, parallel with extraction (Option B). Reads pending nodes without vectors, batches embed via `EmbeddingService`, upserts to Qdrant.
- **Custodian visit asset** (`pipelines/assets/custodian_visit.py`): partitioned by `silo_id`. Runs the visit loop (`custodian/visit.py`), writes `:Claim:Commitment` nodes with R1 evidence.
- **Custodian finalize asset** (`pipelines/assets/custodian_finalize.py`): runs `consensus_promotion.py` to produce `:Finding` from R2 consensus.

### β2c: Clustering + fact-promotion sweep + scheduling

- **Clustering asset** (`pipelines/assets/clustering.py`): runs Leiden + hierarchical summaries. Partitioned by `silo_id`.
- **Fact promotion sweep** — already exists from v1-α; just wire it into the asset graph and add a `ScheduleDefinition` (e.g. hourly per active silo).
- **Scheduling**: full asset graph wired into `pipelines/definitions.py` with sensors on document arrival, schedules on time-based sweeps.

### Done criteria (β2 overall)

- A new document ingested into a silo flows through extraction → embedding → custodian visit → finalize → clustering → fact-promotion without manual intervention.
- Each asset emits structured metrics (rows processed, errors, duration, cost).
- Failed runs retry with backoff; permanent failures land in a poison queue (Redis-backed, TTL).
- `just dagster-web` shows the full graph; manual partition launches succeed.
- Integration test (β5) passes for the e2e flow.

### Out of scope

- Real-time streaming ingest (still batch-pull via sensors).
- Cost-aware scheduling (just rate limits via Dagster's concurrency keys; no spend budgeting).
- Cross-silo reconciliation jobs.

---

## Phase β3: SPLADE hybrid retrieval

**Branch:** `phase-splade`
**Sub-plan:** `v1b-splade.md`
**Team shape:** 2 agents (model wrapper + read-path integration)

### Goal

Add the sparse retrieval channel. Hybrid (dense + sparse) is what the v1 wiki page expects; today only Qdrant dense is wired.

### Tasks

1. **SPLADE encoder** (`embeddings/splade.py`): wrap the SPLADE model (likely `naver/splade-v3` or similar; design pass at kickoff). Async batch encode interface matching the existing `EmbeddingService` protocol shape.
2. **Sparse index store**: decide between Qdrant sparse vectors (Qdrant 1.10+ supports both dense and sparse in the same collection) vs a separate index. **Recommended:** Qdrant sparse vectors — minimizes operational surface.
3. **Read-path fan-in**: extend `engine/qdrant_store.py::query` to perform hybrid search (dense + sparse via Qdrant's `Query` API with fusion). RRF (reciprocal rank fusion) or weighted sum, configurable per silo.
4. **Wiring**: `services/context.py::query` and `lookup` use hybrid by default. MCP `context_query` exposes a `search_mode: "hybrid" | "dense" | "sparse"` param.
5. **Tests**: unit test for SPLADE wrapper; integration test confirms hybrid recall improves over dense-only on a seeded corpus.

### Done criteria

- `context_query` returns hybrid-ranked results by default.
- New embeddings written via the pipeline (β2) carry both dense and sparse vectors.
- Backfill script for existing dense-only nodes (`scripts/backfill_splade.py`, similar shape to `migrate_belongs_to.py`).
- `just check` + `just test` green; integration test passes.

### Out of scope

- Re-ranker on top of hybrid (defer to v1.0).
- Late-interaction models (ColBERT etc.).
- Per-query learned fusion weights.

---

## Phase β4: Migration tooling — silo export/import

**Branch:** `phase-migration-silo-portability`
**Sub-plan:** `v1b-silo-export-import.md`
**Team shape:** 2 agents (export + import in parallel; share a JSON schema)

### Goal

Make silos portable. Knowzilla and Silt onboarding need a way to ship a silo from one environment to another. Generalize the one-shot pattern from `migrate_belongs_to.py`.

### Tasks

1. **Export script** (`scripts/silo_export.py`): emits a JSON Lines file per silo containing all `:Node` and `:Cluster` nodes (with all multi-labels and properties), plus all edges (typed with relationship label). Streaming output so large silos don't OOM. Includes a manifest header with schema version and source environment.
2. **Import script** (`scripts/silo_import.py`): reads the JSONL, validates the manifest (schema version, target environment doesn't already have the silo), creates nodes via `MERGE` (idempotent), recreates edges. Supports `--rename-silo <new_id>` for environment-cloning.
3. **JSON schema**: documented in `architecture/silo-portability.md`. Versioned (`schema_version: 1`). Forward-compat: unknown fields preserved on round-trip.
4. **Vector restoration**: Qdrant vectors are not exported by default (they can be regenerated). Optional `--include-vectors` flag for environments where regeneration is expensive.
5. **Round-trip test**: integration test that exports a seeded silo and imports it into a fresh database; asserts node + edge counts match and a sample `context_query` returns equivalent results.

### Done criteria

- `uv run python -m scripts.silo_export --silo-id <id> --out silo.jsonl` produces a complete dump.
- `uv run python -m scripts.silo_import --in silo.jsonl --target-silo <new_id>` reproduces the silo in another environment.
- Round-trip integration test green.
- Schema documented.

### Out of scope

- Cross-version schema migration on import (just verify schema version matches; defer migration logic until a v2 schema exists).
- Encrypted exports (defer to v1.0 with proper KMS integration).
- Incremental / delta export.

---

## Phase β5: Integration test pack

**Branch:** `phase-integration-test-pack` (or weave into β2 branches)
**Sub-plan:** lighter — list of test cases at kickoff
**Team shape:** 1 agent, runs alongside β2

### Goal

End-to-end coverage against the docker stack. Today's integration tests are scoped to single subsystems (auth, migrations, fact-promotion). v1-β needs a test that exercises the full ingest → query loop.

### Tasks

1. **E2E ingest → query test**: starts the full asset graph in test mode, ingests a small known corpus (3-5 docs), waits for the pipeline to settle, runs `context_query` and `context_get` and `context_provenance` against the resulting state, asserts the canonical answer.
2. **Cross-silo isolation test**: confirms that asserting in silo A and querying in silo B returns nothing — pins the silo-ownership boundary added in β1.
3. **Auth flow test**: mocked WorkOS path through the FastAPI dep + MCP server, asserts dev bypass and prod fail-closed paths.
4. **Failure-mode tests**: extraction LLM unavailable, Qdrant down, Memgraph transient ServiceUnavailable. Confirm the retry/circuit-breaker paths fire correctly.

### Done criteria

- `just test-integration` runs the full pack against the docker stack and passes in CI.
- Each asset family in β2 has at least one integration test exercising its happy path.
- Cross-silo isolation pinned.

### Out of scope

- Load / soak testing (separate concern).
- Chaos testing (out of scope for v1-β).

---

## Phase β6: Paradigm completion + hygiene

**Branch:** `phase-eag-completion`
**Sub-plan:** `v1b-eag-completion.md`
**Team shape:** 2 agents in parallel (paradigm + hygiene tracks)

### Tasks (paradigm)

1. **Wire `primitives.eag.epistemology.supersession`** (`should_supersede`, `detect_contradiction`) into `custodian/supersession.py`. Currently the custodian uses an LLM call for free-text supersession; replace with the structured pure-function path where applicable. Keep the LLM fallback for free-text-only cases.
2. **Wire `primitives.eag.epistemology.confidence`**. Use it for confidence aggregation when a `:Claim` accumulates evidence from multiple sources.
3. **Schedule `claim_to_fact_promotion` Dagster asset.** Add a `ScheduleDefinition` (hourly per silo, or sensor on new claim writes).

### Tasks (hygiene)

4. **WorkOS SDK verify** — final confirmation of the `authenticate_with_session_token` method signature against a real tenant. Pinned SDK version in `pyproject.toml`.
5. **Remove deprecated `custodian.claim_rejections` counter alias.** Targets 2026-Q3 per the TODO. Bump dashboards before removing.
6. **`RelationshipType.CAUSES` ↔ `CITEEdgeType.CAUSES` alignment.** Decide: is the extraction pipeline expected to write EAG semantic edges directly? If yes, replace `RelationshipType` with `CITEEdgeType`. If no, document the deliberate split.
7. **Validator refactor Phase C/D** — defer unless pain emerges. Listed here only so they don't get lost.

### Done criteria

- `primitives.eag.epistemology.*` is fully exercised in production code (was unused before v1-α; partially used after v1-α).
- Fact-promotion runs on a schedule, not just on assert.
- WorkOS path verified against real tenant.
- `RelationshipType.CAUSES` decision documented.
- Old metric alias removed when 2026-Q3 hits (or sooner if dashboards are migrated).

### Out of scope

- Validator refactor Phase C/D — explicitly deferred again.

---

## Cross-cutting concerns

### Dependencies between phases

- β1 unblocks β2, β3, β4 (cleanly — they all need stable auth + silo ownership)
- β2a → β2b → β2c is strictly sequential (later assets read state written by earlier ones)
- β3 (SPLADE) is independent of β2 — runs in parallel
- β4 (migration tooling) is independent of β2 — runs in parallel
- β5 (integration tests) weaves through β2
- β6 is opportunistic — pick items off whenever there's a slot

### Test count growth

Today: 131 unit + ~10 integration. Target by end of v1-β: ~180 unit + ~25 integration. Most of the integration growth is in β5.

### Documentation that lands

- `architecture/silo-portability.md` (β4)
- `docs/dag-architecture.md` updated to reflect actually-shipped DAG (β2c)
- `architecture/README.md` extended with auth + ownership notes (β1)

### Notion wiki updates needed

- v1 page: remove "minimal dashboard" line (UI deferred)
- v1 page: confirm "basic billing" deferred
- Architecture page: add the auth + silo-ownership story when β1 lands

## Suggested team-shape per phase

| Phase | Team size | Parallelism |
|---|---|---|
| β1 | 1 agent | sequential |
| β2a | 2 agents | resources + extraction in parallel |
| β2b | 2 agents | embedding + custodian in parallel |
| β2c | 2 agents | clustering + scheduling in parallel |
| β3 | 2 agents | model wrapper + read-path in parallel |
| β4 | 2 agents | export + import in parallel |
| β5 | 1 agent | runs alongside β2 |
| β6 | 2 agents | paradigm + hygiene tracks |

## Process notes from v1-α to carry forward

- Hostile self-review before merge, every PR. Today caught silent silo discovery miss, security regression in MCP auth, and edge-type mismatch breaking Dagster batch promotion.
- One sub-plan per phase under `context/plans/v1b-*.md`. Master plan (this doc) is the index.
- Devlog at end of each phase (or end of small phase clusters), under `context/devlog/`.
- Strict "don't commit" instruction in agent prompts — at least one v1-α agent committed mid-task and required a `git reset --mixed`. Make this more emphatic.
- Worktree isolation flag for parallel-team agents was unreliable in v1-α (both teammates ended up in the same checkout). Either confirm it works or coordinate via explicit file-level lane assignments in agent prompts.

## When to start

β1 can start any time — it's small and unblocks everything. The Dagster phases (β2) need a short design review at kickoff (concurrency keys, partition shape, retry budgets) before agents touch code.
