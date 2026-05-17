# Codebase Review — 2026-04-30

**Mode**: full
**Scope**: entire `src/context_service/` (~120 Python files, 22k LOC)
**Branch**: `main`   **Base**: `main`   **Active Phase Plan**: none
**Prior review**: `codebase-review-2026-04-28.md` (5 P0, 17 P1)
**Invariants file**: not present
**Agents run**: Logic, Performance, Errors, Security, Architecture (5/7; Plan + Invariants skipped)

## Executive Summary

Major progress since 2026-04-28: **all 5 prior P0s are resolved** (auth split-brain fixed, indexes applied, embedding wired, link() validated, partial N+1 batching). However, **the N+1 in the active extraction path persists** (P0 regression — `apply_document_claims` still fires 2-4 writes per triple). New P1 issues: secrets stored as plain `str` (should be `SecretStr`), store() idempotency race condition, LLM providers lack retry on 429/5xx. Architecture debt accumulates: two `Settings` singletons with different schemas, three hash algorithms for claim IDs, 10 custodian files still bypass protocols.

| Category           | P0    | P1    | P2    | P3    | Total |
| ------------------ | ----- | ----- | ----- | ----- | ----- |
| Logic/Spec         | 1     | 2     | 3     | 1     | 7     |
| Performance        | 1     | 3     | 4     | 1     | 9     |
| Error Handling     | 0     | 2     | 8     | 0     | 10    |
| Security           | 0     | 1     | 3     | 1     | 5     |
| Architecture       | 0     | 3     | 4     | 0     | 7     |
| **Total**          | **2** | **11**| **22**| **3** | **38**|

## Themes

1. **Extraction N+1 persists (P0)** — `apply_document_claims` (the active code path) still loops with 2-4 `execute_write` calls per triple. Entity/rel batching landed but claim writes did not. Findings: R-003.

2. **Secrets exposure risk (P1)** — All LLM/infra API keys are `str` not `SecretStr`; any `Settings.model_dump()` or repr logs them. Findings: S-007.

3. **Idempotency & retry gaps (P1)** — `store()` has check-then-act race on Redis idempotency key; Anthropic/OpenAI providers have no retry on 429/5xx. Findings: E-001, E-002.

4. **Hash algorithm divergence (P2)** — Three files compute claim/finding IDs with sha256, blake2b(32), blake2b(16). Cross-subsystem ID collisions possible. Findings: NA-005.

5. **Protocol bypass ongoing (P1)** — `services/context.py` and 10 custodian files still import `MemgraphClient` directly. `VectorStore` protocol does not exist. Findings: NF-003, NF-006, NA-004.

6. **Two Settings singletons (P1)** — `config/settings.py` and `core/settings.py` both define `Settings` with `lru_cache` singletons. Env changes propagate to only one. Findings: B2, NA-003.

7. **signals/ module is a stub (P1)** — Heat, freshness, priority scoring documented in CLAUDE.md but module is an empty TODO. Findings: L-001.

## Regression Status (from 2026-04-28)

| ID | Finding | Status |
|----|---------|--------|
| S-001/NF-001 | Auth split-brain — every MCP tool raised RuntimeError | **FIXED** — tools use `get_mcp_auth_context()` via WorkOS |
| R-001 | db/indexes.ALL_INDEX_QUERIES never applied at startup | **FIXED** — `apply_all_indexes()` called in lifespan |
| R-002 | Embedding service not wired in api/app.py | **FIXED** — `configure_services(embedding=...)` |
| N-003 | link() Cypher injection | **FIXED** — `RelationshipType` enum validation added |
| R-003/F-016 | N+1 in extraction apply_claims_to_graph | **PARTIAL** — entity/rel batched, but `apply_document_claims` (active path) still N+1 |
| R-004 | clustering/service.py embed() return type mismatch | **FIXED** |
| S-004 | Timing-unsafe token comparison | **FIXED** — uses `hmac.compare_digest` |
| S-005 | SPARQL injection in wikidata.py | **FIXED** — `_escape_sparql_literal()` |
| S-006 | /docs always enabled no auth | **FIXED** — disabled in production |
| N-004 | graph_traversal() relationship filter broken | **FIXED** — parameterization correct |
| N-008 | reason() uses CREATE not MERGE | **FIXED** — MERGE in place |
| N-010 | Extraction job COMPLETED despite claim failures | **FIXED** — guard for total failure added |
| NF-003 | services/context.py bypasses protocols | **NOT FIXED** |
| NF-006 | custodian/ imports MemgraphClient directly | **PARTIAL** — 10 files remain (down from 19) |
| NF-002 | compute_claim_id duplicated | **PARTIAL** — duplication migrated, now 3 algorithms |
| NF-004 | core/service_factory.py dead code | **FIXED** — file removed |
| B1 | pydantic-ai missing from deps | **FIXED** |
| B2 | Two Settings classes overlap | **NOT FIXED** |

---

## Findings

### P0 — Critical (2)

| ID | Location | Issue | Category | Fix | Effort | Verify Exists | Verify Fixed |
|----|----------|-------|----------|-----|--------|---------------|--------------|
| R-003 | `extraction/service.py:489-548` | N+1 in `apply_document_claims` — 2-4 `execute_write` per triple in loop. This is the active code path (`run_extraction_job` → `apply_document_claims`). 20 triples = 60+ round trips. | Perf | Collect all claim rows, single UNWIND for UPSERT_CLAIM, single for ATTACH_CLAIM_TO_PASSAGE. | L | `grep -n "execute_write" extraction/service.py` lines 489-548 | `pytest tests/test_extraction.py -v` + confirm single UNWIND per query type |
| L-001 | `signals/__init__.py:7` | Entire signals module is unimplemented stub. `# TODO: Port heat, freshness, priority from prototype`. Any code importing signal scores gets nothing. | Logic | Port heat/freshness/priority from prototype phase-3. | XL | `cat src/context_service/signals/__init__.py` | Module exports `Heat`, `Freshness`, `Priority` classes |

### P1 — High (11)

| ID | Location | Issue | Category | Fix | Effort | Verify Exists | Verify Fixed |
|----|----------|-------|----------|-----|--------|---------------|--------------|
| S-007 | `config/settings.py:60,64,70,76-78` | All LLM/infra API keys (`qdrant_api_key`, `jina_api_key`, `anthropic_api_key`, `openai_api_key`, `gemini_api_key`, `memgraph_password`) are `str` not `SecretStr`. Any `.model_dump()` or repr exposes them. | Security | Change to `SecretStr`; call `.get_secret_value()` at consumption sites. | M | `grep -n "api_key: str" src/context_service/config/settings.py` | `grep -n "SecretStr" config/settings.py` shows all key fields |
| E-001 | `services/context.py:111-166` | Idempotency key race condition in `store()`. Check-then-act: `get(cache_key)` and `set(cache_key)` are separate Redis ops. Concurrent requests mint duplicate nodes. | Error | Replace with Redis `SET NX EX` (set-if-not-exists). Add `set_nx` to RedisClient. | M | Review lines 111-166 — two separate Redis calls | Single `set_nx` call returns success/failure |
| E-002 | `llm/anthropic.py:100-112`, `llm/openai.py:87-98` | Anthropic/OpenAI providers have no retry on 429/5xx. Single overloaded API window fails all extraction jobs. Jina has correct backoff. | Error | Extract Jina's `_request_with_backoff` pattern into shared helper; apply to LLM providers. | M | `grep -n "retry" llm/anthropic.py llm/openai.py` returns nothing | Both files have backoff decorator/loop |
| L-002 | `mcp/tools/context_query.py:104-106` | Tool description claims time-travel (`as_of`) is supported. It immediately returns `as_of_not_supported` error. False advertising in MCP discovery. | Logic | Change description to "Time-travel (as_of) not yet supported" or implement it. | S | Read `context_query.py:104-106` description string | Description matches behavior |
| L-003 | `mcp/tools/context_query.py:116-118, :93` | Undocumented `search_mode` parameter (`hybrid|dense|sparse`) and response field. Agents cannot discover SPLADE/hybrid mode from the contract. | Logic | Add to `api-examples.md` and tool docstring. | S | `grep -n "search_mode" context_query.py` | Parameter documented in api-examples.md |
| NA-002 | `core/settings.py:19` | `python-dotenv` undeclared dependency. Import `from dotenv import load_dotenv` works by accident via pydantic-settings optional extra. | Arch | Add `python-dotenv>=1.0` to `pyproject.toml`. | S | `grep -n "dotenv" core/settings.py` vs `grep "python-dotenv" pyproject.toml` | `python-dotenv` in pyproject.toml |
| NA-003 | `config/settings.py:68` vs `core/settings.py:700` | Two `get_settings()` singletons diverge at runtime. `custodian/` imports `core.settings`; everything else imports `config.settings`. Env changes propagate to only one. | Arch | Remove `config/settings.py`; re-export `core.settings.get_settings` from `config/__init__.py`. | M | `grep -rn "from context_service.config.settings" src/` vs `grep -rn "from context_service.core.settings" src/` | Single import path used everywhere |
| NA-005 | `extraction/identity.py:8` (sha256), `models/inference.py:52` (blake2b-32), `custodian/consensus_promotion.py:33` (blake2b-16) | Three hash algorithms for claim/finding IDs. Cross-subsystem ID collisions possible. | Arch | Canonicalize on one algorithm (blake2b-32); route all ID computation through one function. | M | Find all `hashlib` imports + digest sizes | Single algorithm used |
| NF-003 | `services/context.py:64-67, 133-143, 223, 293, 536-565` | `ContextService` constructor takes `MemgraphClient`/`QdrantClient` (concrete types). 15+ inline Cypher strings bypass `engine/protocols.py`. | Arch | Type against `HyperGraphStore` protocol; move queries to `db/queries.py`. | L | `grep -n "MemgraphClient" services/context.py` | Import is `HyperGraphStore` from `engine/protocols` |
| NF-006 | `custodian/agents.py:32`, `chain_reader.py:8`, `consensus_promotion.py:14`, `handlers/consensus.py:12`, `promotion.py:25`, `sensors/consensus.py:8`, `silo_synthesis.py:28`, `validators.py:40`, `visit.py:67`, `write_path.py:52` | 10 custodian files still import `MemgraphClient` directly. | Arch | Refactor to protocol; inject via Dagster resources. | L | `grep -rn "MemgraphClient" src/context_service/custodian/` | No direct MemgraphClient imports in custodian/ |
| R-005 | `mcp/tools/context_get.py:72-105` | N+1: per-`node_id` loop calls `ctx_svc.get()` one at a time. `_batch_fetch_nodes` exists but unused here. Hot read path (<20ms target). | Perf | Replace loop with single `_batch_fetch_nodes` call. | M | Read `context_get.py:72-105` — for loop | Single batch call |

### P2 — Medium (22)

| ID | Location | Issue | Category |
|----|----------|-------|----------|
| L-004 | `mcp/tools/silo.py:39` | `silo_create` is silently idempotent (`get_or_create`) but documented as create-only | Logic |
| L-005 | `context_remember.py:89` | `content_type` docstring says `text|utterance|event` but no enum validation; free-form string | Logic |
| L-006 | `services/context.py:845-847` | `context_query` returns empty list with warning log when no embedding; no error to caller | Logic |
| R-006 | `extraction/service.py:564-578` | N+1 in `apply_contradicts_to_graph` — per-pair loop with 1 write each | Perf |
| R-007 | `services/context.py:776-784` | N+1 in `commit_belief` ABOUT edges — per-ref loop | Perf |
| R-008 | `services/context.py:660-669` | N+1 in `assert_claim` evidence edges — per-evidence loop | Perf |
| R-009 | `engine/memgraph_store.py:646-655` | N+1 in `upsert_hyperedge` participants — per-participant loop | Perf |
| E-003 | `services/context.py:985` | `link()` uses CREATE not MERGE — duplicate edges on retry | Error |
| E-004 | `services/context.py:1073-1081` | `graph_traversal()` misses silo_id filter on edge query — potential cross-silo leak | Error |
| E-005 | `services/context.py:78-194` | `store()` accepts empty/whitespace content — invisible to search, no error | Error |
| E-006 | `mcp/tools/context_query.py:25,70` | `top_k` not bounds-checked — `top_k=100000` could OOM Qdrant | Error |
| E-007 | `mcp/tools/context_remember.py`, `context_assert.py` | Accept empty content — silent empty-content nodes | Error |
| E-008 | `services/context.py:432,441,480,492` | `float(r.get("confidence") or 1.0)` — stored `0.0` becomes `1.0`; NaN passes through | Error |
| E-009 | `services/context.py:1049` | `graph_traversal()` depth injected via f-string — callers bypassing MCP have no validation | Error |
| E-010 | `extraction/service.py:254-259` | `_apply_entities_and_rels` silently eats per-type write errors; job still COMPLETED | Error |
| S-008 | `api/auth_dep.py:48` | WorkOS error detail leaked in 401 response — internal state exposed | Security |
| S-009 | `api/routes/health.py:75-114` | `/health?detail=true` unauthenticated — infra enumeration | Security |
| S-010 | `api/auth_dep.py`, `api/deps.py:7` | `get_auth_context` defined but never wired — REST surface unprotected | Security |
| NA-001 | `core/settings.py:148-160` | `WalkerTuning` is dead code — never read outside settings.py | Arch |
| NA-004 | `pipelines/assets/embedding.py:65`, `clustering.py:47` | Import concrete `EngineQdrantStore`; no `VectorStore` protocol exists | Arch |
| NA-006 | `mcp/server.py:19,27-28` | `mcp/server.py` accepts concrete store types in TYPE_CHECKING guard | Arch |
| NA-007 | `core/settings.py:80-100,:202,:414` | `RetrievalTuning` and `RetrievalConfig` both have `rrf_k` — shadowing | Arch |

### P3 — Low (3)

| ID | Location | Issue | Category |
|----|----------|-------|----------|
| L-007 | `api-examples.md` | Response `search_mode` field undocumented (additive, non-breaking) | Logic |
| S-011 | `mcp/auth.py:1-9,143-175` | `MCPAuthMiddleware` dead code with misleading docstring | Security |
| R-010 | `db/indexes.py:136-143` | `apply_all_indexes` opens 1 session per DDL statement — startup only | Perf |

---

## Top Priority Fixes

1. **R-003 (P0)**: Batch extraction writes in `apply_document_claims` with UNWIND queries — this is the active hot path.

2. **L-001 (P0)**: Port signals module from prototype — heat/freshness/priority unimplemented.

3. **S-007 (P1)**: Change all API key fields in `config/settings.py` to `SecretStr`.

4. **E-001 (P1)**: Fix store() idempotency race with Redis `SET NX`.

5. **E-002 (P1)**: Add retry/backoff to Anthropic/OpenAI providers.

6. **NA-003 (P1)**: Consolidate two Settings singletons — remove `config/settings.py`.

7. **NA-005 (P1)**: Standardize on one hash algorithm for claim IDs.

---

## Notes

- **Prior P0s resolved**: All 5 P0s from 2026-04-28 are fixed. Auth split-brain, indexes, embedding wiring, link() injection all resolved.
- **Test suite**: 134 tests pass. Custodian tests now work (pydantic-ai present).
- **SPLADE**: Hybrid retrieval (`search_mode=hybrid|sparse|dense`) is implemented but undocumented.
- **signals/**: Empty stub — any signal-dependent code path silently gets nothing.
