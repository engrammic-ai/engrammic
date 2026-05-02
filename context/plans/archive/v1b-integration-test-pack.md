# Plan: Integration Test Pack

**Status:** ~68% complete (verified 2026-05-02). See audit notes below each task.
**Branch:** `phase-integration-test-pack` (or weave into β2 branches)
**Workstream:** v1-β phase 5 (runs alongside β2)

## Goal

End-to-end integration coverage against the docker stack. Today's integration tests are scoped to single subsystems; v1-β needs tests that exercise the full ingest → query loop and pin the production contracts.

## Why

The current integration suite has ~10 tests (auth, migrations, fact-promotion, p1 fixes). None of them exercise the full pipeline. Without an e2e test, regressions in any one asset can pass CI silently and only surface in production. Cross-silo isolation, auth fail-modes, and asset retry behaviour also lack pinned coverage.

## Current state (anchored from audit on 2026-04-28)

- `tests/integration/conftest.py` — has `docker_available`, `memgraph_client`, `qdrant_client`, `unique_silo_id`, `unique_org_id`, `cleanup_silo` fixtures.
- `tests/integration/test_p1_fixes.py` — exercises previously-broken P1 paths.
- `tests/integration/test_auth_workos.py` — mocked WorkOS verify, dev bypass, fail paths.
- `tests/integration/test_assert_to_fact.py` — assert_claim → promote_claim_to_fact end-to-end (introduced PR #6).
- `tests/integration/test_migrate_belongs_to.py` — migration script (introduced PR #5).
- `just test-integration` runs `pytest -m integration -v`.
- No test exercises the Dagster asset graph, no test pins cross-silo isolation.

## Tasks (priority order)

1. **E2E ingest → query test.** `tests/integration/test_e2e_ingest_query.py`. ⚠️ MISSING — individual operations covered across multiple files but no single unified ingest→query→provenance test exists.
   - Start the full Dagster graph in test mode (after β2c lands) — or in pre-β2 form, drive the asset chain manually via service calls.
   - Ingest 3-5 small docs into a fresh silo with known content (e.g. "Paris is the capital of France", "Berlin is in Germany").
   - Wait for the pipeline to settle (poll for `:Finding` nodes, or hook into Dagster's run-status API).
   - Run `context_query("What is the capital of France?")` and assert top result references the seed doc.
   - Run `context_provenance(claim_id)` and assert it traces back to the seed doc.
   - Run `context_get(claim_id)` and assert metadata is populated.

2. **Cross-silo isolation test.** `tests/integration/test_cross_silo_isolation.py`. ✓ DONE — `test_silo_ownership.py` covers owning org access and foreign org rejection.
   - Assert a claim in silo A as org X.
   - Attempt `context_query` in silo A as org Y → expect `SiloAccessError`.
   - Attempt `context_query` in silo B as org X (different silo, same org) → returns no results from silo A.
   - Pins the silo-ownership boundary added in β1.

3. **Auth flow test (live).** `tests/integration/test_auth_flow.py`. ⚠️ PARTIAL — invalid/missing token paths covered in `test_auth_workos.py`. Missing: dev bypass + prod fail-closed (AUTH_ENABLED=false in production env) tested together in one suite.
   - Boot the full FastAPI app with `AUTH_ENABLED=false`; hit a protected route, assert dev `AuthContext`.
   - Boot with `AUTH_ENABLED=true` + valid `WORKOS_*` env (use mocked WorkOS via the existing `tests/integration/test_auth_workos.py` pattern); hit the route, assert real auth.
   - Boot with `ENVIRONMENT=production AUTH_ENABLED=false` → assert app refuses to start (the boot-time prod-guard).

4. **Failure-mode tests.** `tests/integration/test_failure_modes.py`. ⚠️ PARTIAL — Qdrant failure propagation and circuit breaker behaviour covered in `test_p1_fixes.py`. Missing: extraction LLM unavailable scenario; Memgraph transient ServiceUnavailable with recovery assertion.
   - **Extraction LLM unavailable**: mock the LLM client to raise; run an extraction asset. Assert: asset fails with retry, eventually lands in poison queue (β2c).
   - **Qdrant down**: stop the docker qdrant container mid-test (via fixture); attempt a `context_query`. Assert graceful degradation (returns dense-only or empty with a clear error, depending on β3 fusion config).
   - **Memgraph transient `ServiceUnavailable`**: inject one transient failure via monkey-patching the driver; assert the existing retry policy in `stores/memgraph.py:230-260` recovers.

5. **Asset graph integration tests** (one per asset family in β2). ✓ DONE — `test_extraction_pipeline.py`, `test_hybrid_retrieval.py`, `test_silo_portability.py`, `test_provenance_e2e.py`, `test_assert_to_fact.py`, `test_reflection_e2e.py` all present.
   - `tests/integration/test_extraction_asset.py` — seed docs, run the asset, assert claims land.
   - `tests/integration/test_embedding_asset.py` — seed nodes without vectors, run the asset, assert Qdrant points exist.
   - `tests/integration/test_custodian_assets.py` — seed claims, run visit + finalize, assert findings emerge.
   - `tests/integration/test_clustering_asset.py` — seed findings, run clustering, assert clusters + MEMBER_OF edges.

6. **CI integration step.** Update CI config (`.github/workflows/` or whatever's in use) to run `just test-integration` against a docker-compose stack on PRs that touch `pipelines/`, `engine/`, `services/`, or `stores/`. (Skip for doc-only PRs to keep cycle time tight.)

## Out of scope

- Load / soak testing (separate concern, post-v1).
- Chaos testing.
- Testing UI surfaces (UI is deferred).
- Latency / performance benchmarks (separate harness).

## Done criteria

- E2E ingest → query test passes against the docker stack with the full asset graph.
- Cross-silo isolation test pins the boundary.
- Auth flow test exercises all three modes (dev bypass, prod auth, prod-guard refusal).
- Failure-mode tests cover the three named scenarios.
- Each β2 asset family has at least one integration test.
- `just test-integration` runs in CI on relevant PRs.
- Total integration tests: ~25 (up from ~10 today).
