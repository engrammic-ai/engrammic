# Codebase Review — 2026-04-28

**Mode**: full
**Scope**: entire `src/context_service/` (134 tests, ~120 Python files)
**Branch**: `main`   **Base**: `main`   **Active Phase Plan**: none (v1-alpha complete)
**Prior review**: `codebase-review-2026-04-27.md` (91 findings: 6 P0, 32 P1)
**Invariants file**: not present
**Agents run**: Logic, Performance, Errors, Security, Architecture, Testing (6/7; Invariants skipped)

## Executive Summary

v1-alpha shipped significant progress: **all 13 MCP tools are implemented** (F-001 resolved), auth toggle with prod guard landed (#4), :Claim→:Fact promotion via primitives epistemology wired (#6). However, a critical **auth split-brain** emerged (P0) — every MCP tool call raises `RuntimeError` because two incompatible auth systems coexist. Additionally, **indexes are still never applied** (P0, worse than before), **embedding service is never wired in app.py** (P0, semantic search broken), and **Cypher injection** exists in `link()` (P0). The N+1 pattern in extraction remains unfixed (P0). Testing is blocked by missing `pydantic-ai` dependency.

| Category           | P0    | P1    | P2    | P3    | Total |
| ------------------ | ----- | ----- | ----- | ----- | ----- |
| Logic/Spec         | 0     | 5     | 3     | 1     | 9     |
| Performance        | 2     | 2     | 3     | 1     | 8     |
| Error Handling     | 1     | 2     | 4     | 4     | 11    |
| Security           | 1     | 3     | 5     | 1     | 10    |
| Architecture       | 1     | 4     | 2     | 2     | 9     |
| Testing Blockers   | 0     | 1     | 1     | 3     | 5     |
| **Total**          | **5** | **17**| **18**| **12**| **52**|

## Themes

1. **Auth split-brain (P0)** — `mcp/auth.py` provides `get_mcp_auth()` backed by a ContextVar that `MCPAuthMiddleware` should populate, but the middleware is never mounted. `mcp/server.py` has a separate startup-time global `AuthContext`. All 13 MCP tools call the ContextVar path → `RuntimeError` on every call. Findings: S-001, NF-001.

2. **Indexes defined but never applied (P0)** — `db/indexes.ALL_INDEX_QUERIES` (28+ DDL statements) is never called from app.py lifespan. `bootstrap_custodian_schema()` also never called. Every MATCH on `:Claim(silo_id)`, `:Fact(silo_id)`, `:Document(silo_id)` is a full label scan. F-013 regressed. Findings: R-001.

3. **Embedding service not wired (P0)** — `api/app.py:configure_services()` passes no `embedding=` argument. `ContextService._embedding` is `None`. All `context_query` and `lookup` return empty results silently. F-043 partially regressed. Findings: R-002.

4. **Cypher injection in `link()` (P0)** — `services/context.py:link()` interpolates caller-supplied `relationship` string directly into Cypher f-string with no internal validation. MCP tool validates via enum, but any future caller bypassing MCP is injectable. Findings: N-003, NF-005.

5. **N+1 in extraction still present (P0)** — `apply_claims_to_graph` and `apply_document_claims` still loop over triples issuing 3-4 `execute_write` calls per triple. 20 triples × 2 mentions = 100+ RTTs. F-016 unfixed. Findings: R-003.

6. **api-examples.md is stale** — Uses old tool names (`context_store`, `context_lookup`), wrong parameter names, missing fields. 5 P1 findings. Findings: F-01 through F-05.

7. **Fact promotion dead code for standard agents** — `source_tier` not exposed as MCP parameter; all claims default to `UNKNOWN` tier which fails R1. Findings: F-07.

## Regression Status (from 2026-04-27)

| ID | Finding | Status |
|----|---------|--------|
| F-001 | All MCP tools raised NotImplementedError | **FIXED** — All 13 tools implemented |
| F-006 | Consensus CREATE not MERGE, non-deterministic finding_id | **PARTIAL** — finding_id deterministic, but `CREATE_PROMOTED_FROM_EDGE` still CREATE |
| F-016 | N+1 in apply_claims_to_graph | **NOT FIXED** |
| F-017 | N+1 in lookup (per-result get) | **FIXED** — `_batch_fetch_nodes()` added |
| F-013 | Cluster indexes defined but never applied | **WORSE** — ALL_INDEX_QUERIES never called at startup |
| F-043 | EmbeddingCache ignored | **PARTIAL** — Cache logic in clients, but embedding service never wired |
| F-009 | MCPAuthMiddleware not mounted | **TRANSFORMED** → S-001/NF-001 (auth split-brain) |
| F-010 | Dev mode grants full admin, no env guard | **FIXED** — Settings validator raises in prod |

## Testing Readiness

| Status | Area |
|--------|------|
| Ready | MCP tools (all 13), custodian models/fact_promotion, auth, SiloService |
| Blocked | Custodian visit/agents (`pydantic-ai` not in deps), clustering, extraction pipeline |
| No coverage | Signals (empty), cache, LLM providers, Dagster asset materialize |

**Critical blocker**: `pydantic-ai` missing from `pyproject.toml`. Importing `context_service.custodian` fails at runtime.

---

## Findings

### P0 — Critical (5)

| ID | Location | Issue | Category | Fix |
|----|----------|-------|----------|-----|
| S-001 / NF-001 | `mcp/auth.py:48`, `mcp/server.py:115`, all `mcp/tools/*.py` | Auth split-brain: every MCP tool calls `get_mcp_auth()` which reads a ContextVar never populated (middleware not mounted). Every tool raises `RuntimeError`. | Security / Arch | Mount `MCPAuthMiddleware` in `create_app()`, OR have all tools call `get_mcp_auth_context()` from `server.py` instead. |
| R-001 | `db/indexes.py`, `api/app.py` | `ALL_INDEX_QUERIES` (28+ DDL) never applied at startup. Every query is a full label scan. | Perf | Add `apply_all_indexes(memgraph)` call in app lifespan after DB connection. |
| R-002 | `api/app.py:54-58` | `configure_services()` passes no `embedding=`. `ContextService._embedding` is `None`. Semantic search silently returns empty. | Perf | Build `EmbeddingService` via `ServiceFactory._create_embedding_service()` during lifespan; pass to `configure_services(embedding=...)`. |
| N-003 | `services/context.py:912-919` | `link()` interpolates `relationship` string directly into Cypher f-string with no internal validation. Cypher injection if called outside MCP. | Error/Security | Add allowlist validation inside `link()` itself (check against `RelationshipType`). |
| R-003 / F-016 | `extraction/service.py:320-399, 457-532` | `apply_claims_to_graph` / `apply_document_claims` still N+1: 3-4 `execute_write` per triple. 100+ RTTs per extraction job. | Perf | Batch with UNWIND queries; collapse to 3-4 total queries. |

### P1 — High (17)

| ID | Location | Issue | Category |
|----|----------|-------|----------|
| F-01 | `context/api-examples.md` | Stale tool names: `context_store`, `context_lookup`, `context_store_chain` don't exist. | Logic |
| F-02 | `context/api-examples.md` | Parameter mismatches: `from_node_id` vs `from_node`, `top_k` vs `max_nodes`. | Logic |
| F-03 | `context/api-examples.md` | `silo_create` contract wrong: `org_id`, `config` not actual params. | Logic |
| F-05 | `mcp/tools/context_get.py:75-85` | Response missing documented fields: `layer`, `summary`, `confidence`, `tags`, `created_at`. | Logic |
| F-07 | `mcp/tools/context_assert.py:97-112` | `source_tier` not exposed as MCP param; auto-promotion to :Fact dead code for standard agents. | Logic |
| R-004 | `clustering/service.py:372` | `embed()` returns `list[list[float]]` but code unpacks as `(vectors, _usage)`. Runtime crash. | Perf |
| N-004 | `services/context.py:999-1002` | `graph_traversal()` relationship filter broken: `"|".join(types)` produces `IN ['A|B']` not `IN ['A','B']`. | Error |
| N-010 | `extraction/service.py:396-397` | Job marked `COMPLETED` even if all claim writes failed. Claims silently lost. | Error |
| S-002 | `mcp/auth.py:78-87` | Dev mode fallback has no env guard at `validate_mcp_request()` level. Misconfigured prod is full-admin. | Security |
| S-003 | `auth/resolve.py:58` | MCP auth uses single process-wide static token. No per-request auth; rotation requires restart. | Security |
| S-004 | `mcp/auth.py:101` | `token != expected_key` is timing-unsafe. Use `hmac.compare_digest`. | Security |
| NF-003 | `services/context.py` | Bypasses `engine/protocols.py` — takes raw `MemgraphClient`, issues 15+ inline Cypher strings. | Arch |
| NF-006 | `custodian/` (19 files) | Entire subsystem imports `MemgraphClient` directly, bypassing protocols. | Arch |
| NF-009 | `services/context.py` | 12+ inline Cypher strings that belong in `db/queries.py`. | Arch |
| B1 | `pyproject.toml` | `pydantic-ai` missing from dependencies. Importing `custodian` fails at runtime. | Testing |

### P2 — Medium (18)

| ID | Location | Issue | Category |
|----|----------|-------|----------|
| F-04 | `context/api-examples.md:395-405` | Perf targets use old tool names. | Logic |
| F-06 | `mcp/tools/context_get.py:30`, `context_query.py:122` | `as_of` time-travel param silently ignored. | Logic |
| F-12 | `mcp/tools/context_get.py:51-65` | `silo_id` param validated but ignored (always uses derived silo). | Logic |
| R-005 | `custodian/consensus_promotion.py:46-51` | Per-chain `CREATE_PROMOTED_FROM_EDGE` not batched. | Perf |
| R-006 | `clustering/service.py:164-177` | `build_hierarchy` per-cluster writes not batched. | Perf |
| R-007 | `clustering/service.py:383-399` | Qdrant upserts one-by-one despite batch API. | Perf |
| N-001/N-011 | `engine/queries.py:1086-1091` | `CREATE_PROMOTED_FROM_EDGE` uses CREATE not MERGE. Duplicate edges on retry. | Error |
| N-008 | `services/context.py:516-537` | `reason()` uses CREATE not MERGE. Duplicate ReasoningChain on retry. | Error |
| N-009 | `services/context.py:171-173` | Idempotency cache written after Qdrant. Duplicate nodes on Redis failure. | Error |
| N-012 | `stores/memgraph.py:118-133` | `transaction()` has no retry on transient errors. | Error |
| S-005 | `extraction/filter/wikidata.py:32-33` | SPARQL injection via unescaped newlines/single-quotes. | Security |
| S-006 | `api/app.py:97-99` | `/docs`, `/redoc`, `/openapi.json` always enabled, no auth. | Security |
| S-007 | `auth/workos_client.py:28,37` | WorkOS SDK method unconfirmed (TODO comment). | Security |
| S-008 | `auth/workos_client.py:28` | `workos_api_key` as `str` not `SecretStr`. | Security |
| S-010 | `db/queries.py` | Cypher query builders still accept arbitrary strings (mitigated at caller). | Security |
| NF-002 | `engine/queries.py:953-973`, `models/inference.py:52-72` | `compute_claim_id` duplicated with diverging signatures. | Arch |
| NF-008 | `services/context.py:130-142` | `_ALLOWED_NODE_TYPES` f-string fragile if special chars added. | Arch |
| B2 | `config/settings.py`, `core/settings.py` | Two separate `Settings` classes with overlapping fields. | Testing |

### P3 — Low (12)

| ID | Location | Issue | Category |
|----|----------|-------|----------|
| F-10 | `custodian/supersession.py` | `detect_contradiction` not wired (known, deferred). | Logic |
| R-008 | `embeddings/jina.py:162-168` | `EmbeddingCache.get()` called in loop, no mget batch. | Perf |
| N-002 | `services/context.py:131` | `node_type` f-string guarded but pattern fragile. | Error |
| N-005 | `custodian/supersession_parser.py:87` | Confidence not clamped to [0,1]. | Error |
| N-006 | `extraction/filter/circuit_breaker.py:14` | `asyncio.Lock()` at module level (latent multi-loop hazard). | Error |
| N-007 | `extraction/filter/llm_classifier.py:85` | Redundant `TimeoutError` in except clause. | Error |
| S-009 | `config/settings.py:25` | Default `host=0.0.0.0` binds all interfaces. | Security |
| NF-004 | `core/service_factory.py:37-218` | `ServiceFactory` dead code, never called. | Arch |
| NF-007 | `mcp/tools/context_get.py`, `context_provenance.py` | Import inconsistency (runtime vs module level). | Arch |
| B3 | `auth/workos_client.py` | WorkOS not validated against real SDK (nice-to-have). | Testing |
| B4 | `signals/__init__.py` | Module empty (minor). | Testing |
| B5 | `core/service_factory.py` | 8 commented-out factory methods (minor). | Testing |

---

## Top Priority Fixes

1. **S-001/NF-001 (P0)**: Fix auth split-brain — have tools call `get_mcp_auth_context()` from `server.py` (2-line change per tool) OR mount middleware.

2. **R-001 (P0)**: Add `apply_all_indexes()` call in app lifespan.

3. **R-002 (P0)**: Wire embedding service in `api/app.py:configure_services()`.

4. **N-003 (P0)**: Add validation inside `link()` against `RelationshipType` enum.

5. **R-003 (P0)**: Batch extraction writes with UNWIND queries.

6. **B1 (P1)**: Add `pydantic-ai` to `pyproject.toml` dependencies.

7. **S-004 (P1)**: Replace `token != expected_key` with `hmac.compare_digest` (2-line fix).

---

## Notes

- **MCP tools**: All 13 implemented and working (when auth is fixed). Major improvement from yesterday.
- **Primitives epistemology**: `should_promote_r1`/`should_promote_r2`, `noisy_or_aggregate` now wired in fact_promotion and consensus handlers.
- **:Finding filter**: CLAUDE.md rule 7 now compliant across all read queries.
- **Test suite**: 134 tests pass. Good coverage for MCP, auth, fact promotion. Gaps in clustering, extraction, signals.
