# Codebase Review - 2026-05-14

**Mode**: full (branch state, no diff vs main)
**Branch**: `feat/heat-diffusion`
**Active plans**:
- `docs/superpowers/plans/2026-05-14-sage-job-consolidation.md`
- `docs/superpowers/specs/2026-05-14-sage-job-consolidation.md`
- `context/architecture/sage-system.md`
**Previous review**: 2026-05-09 (4 P0, 17 P1, 17 P2, 7 P3)
**Linter baseline**: ruff clean (0 issues)
**Agents run**: 6 (Logic+Plan, Perf, Errors, Security+Regression, Architecture+Impact, AI/LLM)

---

## Executive Summary

**Headline:** Three of four prior P0s from 2026-05-09 are **RESOLVED** (Cypher injection, admin auth stubs, skills unique index). However the **SAGE job consolidation plan is essentially un-started** despite its spec/plan being committed in 85ca666/62317b8, and a **new auth bypass** (admin API key defaulting to `None` silently grants access) has been introduced.

| Category | P0 | P1 | P2 | P3 |
|----------|----|----|----|----|
| Logic / Spec / Plan | 3 | 3 | 2 | 1 |
| Performance | 0 | 5 | 4 | 3 |
| Error Handling | 0 | 5 | 6 | 4 |
| Security | 1 | 0 | 1 | 2 |
| Architecture / Blast Radius | 0 | 4 | 6 | 4 |
| AI / LLM | 1 | 4 | 5 | 4 |
| **Total** | **5** | **21** | **24** | **18** |

## Top 5 (effort-weighted)

1. **[P0/M] SAGE plan not implemented** — `pipelines/schedules.py`, `pipelines/sensors/__init__.py`. The branch is named `feat/heat-diffusion` and recent commits batch-refactored belief jobs, but the 3 SAGE schedules don't exist, the 7 targeted sensors are still exported, and `heat_diffusion` + `prewarm_sweep` aren't wired into any schedule. Either finish the plan or remove the plan/spec docs to stop the drift.
2. **[P0/S] Admin auth bypass via `None` default** — `api/routes/admin.py:26-35`. If `SECURITY__ADMIN_API_KEY` is unset in production, `_require_admin_key()` silently returns and every `/admin/*` route is open. Add a `settings.is_production()` guard that refuses startup or hard-fails the request.
3. **[P0/S] Redis fail-open in reflection rate limiter** — `engine/reflection_triggers.py:78-86`. Exception path returns `True`, removing the rate limit entirely if Redis blips. With LLM costs as the rate-limited resource, this is unbounded cost exposure. Fail closed; add a circuit breaker before fail-open is acceptable.
4. **[P1/S] N+1 storms in pipeline assets** — `llm_pattern_detection.py:139-149` (per-cluster facts), `custodian_finalize.py:74-86` (per-commitment chains), `auto_tagging.py:156-175` (per-node tag write), `extraction.py:145-148` (per-doc mark). Each is a single `UNWIND $ids` rewrite. Bundled fix is <4h and yields 5-10x asset speedup.
5. **[P1/M] Timeout gaps across LLM + embedding boundary** — `llm/litellm_provider.py:82-87, 124-129`, `embeddings/litellm_embeddings.py:144-145`, `expansion/generator.py:59`, `engine/revision.py:357, 521`, `engine/summarization.py:97`. No defaults; relies on callers. Set default `timeout=60s` at the provider layer so missing-timeout at call sites becomes a non-issue.

## Themes

1. **Plan drift on SAGE consolidation** (4 findings, P0-P2). The plan is written and committed, the work is not. The recent batch refactors in `belief_merge.py` / `belief_synthesis.py` look like _half_ of the consolidation — a clear partial-execution state that needs either commit or rollback.
2. **Fail-open / silent-swallow patterns** (8 findings, P0-P2). Redis errors, claim promotion failures, embedding failures, evidence validation partial-success — multiple sites convert errors into apparent success. Cumulatively this is the largest reliability risk.
3. **N+1 + sequential LLM in pipeline assets** (9 findings, P1-P2). Batch consolidation refactor stopped at the silo boundary — the per-cluster / per-commitment / per-doc inner loops are still serial. Single template change (`UNWIND`) fixes most.
4. **Protocol abstraction erosion** (8 findings, P1-P2). MCP tools call `db/queries.py` directly, pipeline assets import concrete `MemgraphClient`/`RedisClient`, cache modules reach past services to stores. CLAUDE.md rule 4 violated in three distinct layers.
5. **LLM cost/safety scaffolding incomplete** (6 findings, P0-P2). No per-silo cost budget enforcement, unbounded embedding inputs, no grounding check on synthesized beliefs, no anthropic prompt-cache markers despite hot system prompts.

## Blast Radius Hotspots

| File | Importer count | Has tests? | Risk | Notes |
|------|----------------|-----------|------|-------|
| `config/settings.py` | 44+ | unknown | HIGH | Critical singleton; admin auth bug lives here |
| `config/logging.py` | 35 | unknown | HIGH | structlog factory; central |
| `pipelines/resources.py` | 28 | likely | MEDIUM | Resource factory; protocol-correct |
| `pipelines/partitions.py` | 23 | likely | MEDIUM | Stable silo partition def |
| `stores/redis.py` | 15+ | unknown | MEDIUM | Should go through cache protocol; 5 cache classes bypass services |
| `services/models.py` (`derive_silo_id`) | 11 | no | CRITICAL | Tenant isolation key; no test file |
| `db/queries.py` (Cypher templates) | 9+ | no | CRITICAL | Architecture violation — MCP tools import directly |
| `telemetry/metrics.py` | 11 | unknown | MEDIUM | Fire-and-forget; failures silent |

## Regression Status (from 2026-05-09)

| ID | Issue | Status | Evidence |
|----|-------|--------|----------|
| S-001 | Cypher injection in tombstone/admin | **FIXED** | `engine/tombstone.py:50-52` uses `$edge_type` parameterization |
| Auth-1 | Skills API auth stubs no-op | **MITIGATED** | Now returns 501 instead of granting access; still needs implementation |
| MT-1 | `UNIQUE(name)` breaks multi-tenancy | **FIXED** | Migration `385b53d0c0c0` creates `UNIQUE(name, silo_id)` |
| PI-1 | Prompt injection in silo_synthesis entity fallback | **FIXED** | `escape_for_prompt()` applied |
| TO-1 | No wall-clock timeout on `agent.run()` calls | **PARTIAL** | Some sites have `asyncio.wait_for`; provider-level default still missing |
| L-001 | Auto-promote threshold | not re-verified this review | — |
| L-002 | `context_reason` bypass | not re-verified this review | — |

---

## Findings

### Logic, Spec & Plan Conformance

| ID | Priority | Location | Issue | Recommendation |
|----|----------|----------|-------|----------------|
| L-01 | **P0** | `pipelines/schedules.py:47-138` | SAGE schedules (`sage_custodian`, `sage_synthesizer`, `sage_groundskeeper`) not present; old `custodian_pipeline`, `knowledge_pipeline`, `clustering_pipeline`, `heat_pipeline` schedules retained | Implement plan Task 2-4 OR remove plan/spec to stop documentation drift |
| L-02 | **P0** | `pipelines/schedules.py:119-138` | `heat_pipeline_schedule` targets only `heat`, `edge_heat`, `weak_link_review` — `heat_diffusion` and `prewarm_sweep` are orphaned (no schedule, no sensor) | Add to groundskeeper schedule per spec lines 88-92 |
| L-03 | **P0** | `pipelines/sensors/__init__.py:1-29` | 7 sensors targeted for deletion in plan Task 6 are still exported and active. On deploy these will dual-fire with any future SAGE schedules | Either delete now (per plan) or document that consolidation is paused |
| L-04 | P1 | `mcp/server.py:126` | Direct import of concrete `PostgresStore` — violates CLAUDE.md rule 4 | Inject via protocol; see ARCH-01 |
| L-05 | P1 | `engine/chain_saga.py:12` | `TYPE_CHECKING` import of `PostgresStore` | Use protocol type even under TYPE_CHECKING |
| L-06 | P1 | `pipelines/resources.py:164` | Imports concrete `QdrantClient` | Depend on store protocol |
| L-07 | P2 | `pipelines/assets/belief_synthesis.py:27`, `belief_merge.py:25`, `llm_pattern_detection.py` | Hardcoded batch limits (50, 30, 50) without documented rationale | Centralize in `settings` or `resources`; comment tuning intent |
| L-08 | P2 | `pipelines/assets/heat_diffusion.py:34` | `concurrency_key: "heat_diffusion"` is global rather than silo-partitioned | Use `concurrency_key=f"heat_diffusion:{silo_id}"` or rely on partition concurrency |
| L-09 | P3 | `mcp/tools/__init__.py:50-63` vs `CLAUDE.md:62-73` | Tool registration includes `context_get`, `context_graph`, `context_query`, `context_history` not in the documented 10-tool surface | Reconcile CLAUDE.md or remove undocumented tools |

### Performance

| ID | Priority | Location | Issue | Recommendation | Impact |
|----|----------|----------|-------|----------------|--------|
| P-01 | P1 | `pipelines/assets/llm_pattern_detection.py:139-149` | N+1 cluster facts fetch in `for` loop | Single `UNWIND $cluster_ids` query | ~250ms→50ms |
| P-02 | P1 | `pipelines/assets/custodian_finalize.py:74-86` | N+1 chain fetch per commitment | `UNWIND $commitment_ids` | ~150ms→20ms |
| P-03 | P1 | `pipelines/assets/auto_tagging.py:156-175` | N+1 tag writes per node | Batch `UNWIND $updates` with SET | ~500ms→50ms |
| P-04 | P1 | `pipelines/assets/extraction.py:145-148` | Per-doc `_MARK_DOC_EXTRACTED` write | `UNWIND $doc_ids` | ~250ms→10ms |
| P-05 | P1 | `pipelines/assets/belief_synthesis.py:93-102` | Sequential LLM call per cluster (50× 3-5s) | `asyncio.gather` with semaphore (3-5 concurrent), respect rate limits | 150s→30-50s |
| P-06 | P2 | `pipelines/assets/extraction.py:159-164` | Per-relationship `resolve_alias` calls | Batch multi-get | ~50ms/doc |
| P-07 | P2 | `mcp/tools/context_store.py:573-590` | Embeddings computed without cache check | Use existing `embedding_cache` before `.embed()` | 20-50ms per dup |
| P-08 | P2 | `services/context.py:1655-1672` | Graph depth-2 traversal scans without index hint on `(silo_id, id)` | Add index, use index hint | ~200ms→50ms |
| P-09 | P2 | `mcp/tools/context_graph.py:81-95` | Sequential `emit_edge_access_event` (already parallel for nodes) | `asyncio.gather` on edges | ~100ms→10ms |
| P-10 | P3 | `services/context.py:1633-1651` | Unbounded BFS for depth+seeds product | Add early `nodes_visited > max_nodes` termination | depth-3 large seeds |
| P-11 | P3 | `mcp/tools/context_store.py:44-49` | `build_embedding_service()` per embed call | Reuse via request-scoped or singleton | 5-10ms |
| P-12 | P3 | `mcp/tools/context_get.py:173-179` | Redis emit_access blocks recall hot path | Fire-and-forget via task | ~20ms |

### Error Handling & Resilience

| ID | Priority | Location | Issue | Fix |
|----|----------|----------|-------|-----|
| E-01 | **P0/security** | `engine/reflection_triggers.py:78-86` | Redis rate-limit check fails open (`return True` on exception) | Fail closed; circuit breaker before any fail-open behavior |
| E-02 | P1 | `mcp/tools/context_store.py:297-302` | Claim promotion exception logged-and-swallowed; flag stays False but caller sees success | Retry with backoff, or surface error in response |
| E-03 | P1 | `llm/litellm_provider.py:82-87, 124-129` | No default timeout on `litellm.acompletion()` / `aembedding()` | Add `timeout=60s` default in `_build_kwargs` |
| E-04 | P1 | `embeddings/litellm_embeddings.py:144-145` | No timeout on `aembedding` | Pass `timeout=60.0` |
| E-05 | P1 | `expansion/generator.py:59`, `engine/revision.py:357, 521`, `engine/summarization.py:97` | `.complete()` without timeout in 4 places | Add `timeout=30-60s` |
| E-06 | P1 | `engine/chain_applicability.py:129-131` | Embedding failure returns `[]` without context | Log session_id, raise or return typed error |
| E-07 | P2 | `services/silo.py:47-49` | Check-then-act on silo creation; race-prone | `MERGE ... ON CREATE SET ...` |
| E-08 | P2 | `db/indexes.py:200-201` | `CREATE INDEX` swallows all exceptions, not just "already exists" | Inspect error code; re-raise unknowns |
| E-09 | P2 | `stores/redis.py:114-120` | No retry on transient Redis errors | tenacity-backed retry decorator |
| E-10 | P2 | `mcp/tools/context_store.py:255-266` | `asyncio.gather` evidence validation can leave partial-success path | Treat any failure as a halt |
| E-11 | P2 | `mcp/tools/context_store.py:237-238, 691-692` | Confidence bounds enforced but not NaN/Inf | `math.isfinite()` after float cast |
| E-12 | P2 | `pipelines/assets/step_embedding.py:142-144` | Qdrant update silently leaves vectors empty on failure | Exponential backoff retry; queue for async retry |
| E-13 | P3 | `pipelines/sensors/session_autoclose.py:68-70` | Per-session failure doesn't stop sensor (intentional?) — undocumented | Add comment; emit metric on partial failure |
| E-14 | P3 | `custodian/visit.py:691-694` | Deep-pass agent `TimeoutError` terminates visit; no degraded fallback | Return partial results on timeout |
| E-15 | P3 | `mcp/tools/context_update_belief.py:27-28` | No empty/null check on `belief_id` | Validate before query |
| E-16 | P3 | `config/settings.py:81, 92, 120` | Timeouts hardcoded; no ENV override | Make env-overridable |

### Security

| ID | Priority | Location | Vector | Severity | Remediation | Regression-of |
|----|----------|----------|--------|----------|-------------|---------------|
| S-01 | **P0** | `api/routes/admin.py:26-35` | Auth bypass — `admin_api_key is None` silently allows access | Critical | Add `if settings.is_production() and configured_key is None: raise HTTPException(503)` at startup or per request | NEW |
| S-02 | P2 | `api/routes/skills.py:22-33` | Skills routes stubbed with 501 — endpoints non-functional | Medium | Implement auth or remove routes from prod build | Prior |
| S-03 | P3 | `config/settings.py:473` + `api/app.py` | `cors_origins` configured but `CORSMiddleware` never registered | Low | Wire middleware; verify default origin policy for prod | NEW |
| S-04 | P3 | `db/postgres.py:38-53` | Default postgres credentials `context/context` | Low (dev-only) | Validator should require non-default in production | Pre-existing |
| (resolved) | — | `engine/tombstone.py` | Cypher injection | — | Fixed via `$edge_type` parameter | S-001 (2026-05-09) |
| (resolved) | — | `alembic/.../385b53d0c0c0_add_skills_table.py:50` | Multi-tenant unique index | — | Fixed: `UNIQUE(name, silo_id)` | (2026-05-09) |
| (resolved) | — | `custodian/silo_synthesis.py` | Prompt injection in entity fallback | — | `escape_for_prompt()` applied | (2026-05-09) |

### Architecture & Blast Radius

| ID | Priority | Location | Issue | Recommendation |
|----|----------|----------|-------|----------------|
| ARCH-01 | P1 | MCP tools (`context_store.py`, `context_admin.py`, `context_recall.py`, `context_get.py`) | Direct `execute_write()` / `execute_query()` calls bypass service layer | Route through `ContextService` / `engine/services`; MCP should never touch `db/queries.py` |
| ARCH-02 | P1 | `pipelines/assets/*` (extraction, custodian_visit, clustering, custodian_finalize) | Direct `RedisClient` / `MemgraphClient` imports | Provide `RedisResource` and `HyperGraphStore` protocol; inject via Dagster resources |
| ARCH-03 | P1 | `cache/*` (lookup_cache, node_cache, alias_cache, embedding_cache, silo_ownership_cache) | All 5 caches import `RedisClient` directly | Add `CacheStore` protocol in `engine/protocols.py`; inject |
| ARCH-04 | P1 | `custodian/*` (write_path, visit, dispatch, proposal_worker) | Custodian core executes raw Cypher | Wrap in `CustodianStore` service implementing protocol |
| ARCH-05 | P2 | `services/models.py::derive_silo_id` | Hardcoded UUID v5 hash, no strategy pattern; tenant isolation single point of failure | Introduce `SiloDerivationStrategy` protocol; explicit tests |
| ARCH-06 | P2 | `db/postgres.py` | Module-level `_engine`, `_session_factory`, `_init_lock` — async startup race risk | Wrap in `PostgresSessionManager`; per-request context var |
| ARCH-07 | P2 | `mcp/server.py::configure_services` | Lazy init of `PostgresStore` on first access | Require explicit registration; fail-fast on missing |
| ARCH-08 | P2 | MCP tools return type | All return `dict[str, Any]` for both success and error | Define `TypedDict` / Pydantic `Result` models |
| ARCH-09 | P2 | `db/queries.py` + `db/custodian_queries.py` | Cypher split across two files, no index | Consolidate into `db/query_catalog.py` or add docstring index |
| ARCH-10 | P2 | `custodian/write_path.py` | Finding nodes created directly; no propose→crystallize intermediate like other Wisdom-layer writes | Wrap in `ProposedFinding` if consistency matters |
| ARCH-11 | P3 | `pipelines/assets/proposal_cleanup.py` | Single-pass query, no retry | Add backoff + metric |
| ARCH-12 | P3 | `telemetry/metrics.py` | Fire-and-forget; failures silent — masks instrumentation bugs | Optional `strict=True` for tests |
| ARCH-13 | P3 | Job stores (`extraction/filter/wikidata.py`, `clustering/job_store.py`) | Direct `RedisClient` | `JobQueue` protocol |
| ARCH-14 | P3 | `config/logging.py` | Undocumented `_dagster_context` `ContextVar` for log routing | Docstring; document ContextVar lifetime |

### AI / LLM

| ID | Priority | Location | Issue | Fix |
|----|----------|----------|-------|-----|
| AI-01 | **P0** | `pipelines/assets/embedding.py:143` | Node content embedded without size cap → token / cost explosion | Truncate to 8K chars (or model-specific token count) before embedding |
| AI-02 | P1 | `engine/revision.py:357, 521`, `engine/summarization.py:97`, `expansion/generator.py:59` | `.complete()` missing timeouts | See E-05 — fix at provider layer |
| AI-03 | P1 | `engine/revision.py:367` | Fact-cluster content embedded without per-item size cap | Limit each item to ~2K chars |
| AI-04 | P1 | `engine/synthesis.py:82` | Fact content concatenated into prompt without truncation | Truncate each fact (~100 chars) before prompt assembly |
| AI-05 | P1 | `extraction/service.py:114-117` | No pre-call token count; silently truncates over `max_tokens` | tiktoken count; reject or chunk |
| AI-06 | P2 | `engine/synthesis.py:152-159` | LLM-synthesized belief used directly without grounding check vs input facts | Verify belief references input fact IDs / spans |
| AI-07 | P2 | `pipelines/assets/auto_tagging.py:72` | Batch (50) bounded but per-node content not truncated | Add per-item truncation |
| AI-08 | P2 | Per-silo cost enforcement absent | Costs tracked but no budget check before LLM call | `check_silo_cost_budget()` gate |
| AI-09 | P2 | `engine/llm_patterns.py:143-154` | Cluster facts truncated to 50 — context-loss risk on large clusters | Bump to 100 or pre-summarize |
| AI-10 | P2 | `llm/litellm_provider.py:82-90` | No retry on 429/503 | tenacity backoff (3 attempts) on rate limit / 5xx |
| AI-11 | P3 | `engine/synthesis.py:59-65` | System prompt re-sent every call; no anthropic `cache_control: ephemeral` | Add cache marker on stable system blocks |
| AI-12 | P3 | `engine/llm_patterns.py:209-220` | Unknown / low-confidence (<0.3) patterns silently dropped | Emit metric / audit log |
| AI-13 | P3 | `embeddings/litellm_embeddings.py:144-155` | Embedding failure cascades to asset failure | Skip-and-record fallback for non-critical paths |
| AI-14 | P3 | `extraction/service.py:120` | Truncated error log + full exception re-raise | Sanitize re-raised exception payload |

---

## Suggested Next Actions

1. **Decide SAGE consolidation fate** (1h): finish it on this branch, or rebase the plan/spec docs onto a separate branch so `main` doesn't carry an un-started commitment. The recent batch refactors look like partial execution; that ambiguity is itself a finding.
2. **One-line fix for S-01** (10min): guard `admin_api_key is None` in production at startup. This is the only true P0/Security in the diff and ships in minutes.
3. **N+1 sweep PR** (≤4h): bundle P-01..P-04, all single-template `UNWIND` rewrites. Add a regression test that counts queries per asset run.
4. **Provider-level timeout default** (1h): one change in `llm/litellm_provider.py` + `embeddings/litellm_embeddings.py` collapses E-03/E-04/E-05/AI-02 into one fix.
5. **Reflection rate-limit fail-closed** (1h): E-01. Pair with simple Redis health metric so circuit breaker can be added later.

## Items Deferred / Not Re-verified

- Prior L-001 (auto-promote threshold enforcement) and L-002 (`context_reason` bypass) were not re-checked this run.
- No invariants file (`context/review/invariants.md`) and no false-positive log exist — consider seeding them; the patterns in ARCH-01..04 (protocol violations) and E-01 (fail-open Redis) are good invariant candidates.
