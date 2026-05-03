# Codebase Review - 2026-05-03

**Mode**: full
**Branch**: main  **Base**: main
**Plan**: none active
**Previous review**: 2026-04-27 (91 findings: 6 P0, 32 P1, 38 P2, 15 P3)
**Linter baseline**: ruff/mypy (run via `just check`)

## Executive Summary

Significant progress since the April review: all 8 previously identified P0/P1 items are now fixed (MCP tools implemented, consensus promotion atomicity, auth wiring, retry logic, resource teardown). However, this review surfaces new critical issues, primarily around **prompt injection vulnerabilities** in the extraction/clustering pipelines (AI-001/002/003), **cross-silo data leaks** in clustering queries (B-001), and **N+1 hot loops** that will cause performance collapse at scale (P-001/002).

| Category | P0 | P1 | P2 | P3 | Total |
|----------|----|----|----|----|-------|
| Logic | 0 | 2 | 2 | 3 | 7 |
| Performance | 2 | 5 | 3 | 2 | 12 |
| Error Handling | 1 | 4 | 3 | 1 | 9 |
| Security | 3 | 4 | 3 | 1 | 11 |
| Architecture | 0 | 0 | 4 | 3 | 7 |
| Blast Radius | 4 | 0 | 7 | 0 | 11 |
| AI/LLM | 3 | 5 | 4 | 1 | 13 |
| Docs | 0 | 0 | 5 | 3 | 8 |
| **Total** | **13** | **20** | **31** | **14** | **78** |

## Themes

1. **Prompt injection across the LLM surface** (AI-001, AI-002, AI-003) - P0. User content is interpolated into prompts via `.format()` without escaping. Attacker-controlled claims/documents can hijack extraction, classification, and summarization.

2. **Cross-silo data leaks in clustering** (B-001, B-002) - P0. `CREATE_MEMBER_OF` matches nodes without `silo_id` constraint; UUID collision links nodes across tenants. `DELETE_CLUSTERS` count is always 0 after DETACH DELETE.

3. **N+1 hot loops in sensors and assets** (P-001, P-002, P-007) - P0/P1. Consensus sensor issues up to 1000 individual queries per tick. Clustering PART_OF edges written one at a time despite batch query existing.

4. **Single-pass asset truncation** (P-003, P-004) - P1. Embedding and extraction assets process only 50-100 items per run, causing unbounded backlog growth on active silos.

5. **Qdrant/Memgraph desync** (E-001) - P0. Memgraph write succeeds, then if Qdrant upsert fails, node is graph-reachable but invisible to vector search forever.

6. **Auth middleware still not mounted** (S-001) - P0. Per-tool auth is the only enforcement; any tool missing `get_mcp_auth_context()` is silently unauthenticated.

7. **PII in error logs** (S-007, AI-013) - P1. All 4 LLM clients log raw `e.response.text` which can echo user content.

## Regression Status

All 8 P0/P1 items from 2026-04-27 review are **FIXED**:

| ID | Status | Note |
|----|--------|------|
| F-001 | Fixed | All 15 MCP tools implemented and registered |
| F-006 | Fixed | Consensus promotion uses deterministic ID + transaction |
| F-007 | Fixed | execute_write has tenacity retry |
| F-008 | Fixed | execute_query retries ServiceUnavailable |
| F-009 | Fixed | Auth via get_mcp_auth_context per-tool |
| F-010 | Fixed | Dev bypass gated behind auth_enabled=false + production guard |
| F-021 | Fixed | All documented MCP tools exist |
| F-022 | Fixed | Teardown uses _close_async with loop guard |

## Blast Radius Hotspots

| File | Importers | Test Coverage | Risk |
|------|-----------|---------------|------|
| config/settings.py | 37 | partial | high |
| config/logging.py | 32 | no | medium |
| engine/protocols.py | 30 | no | high |
| utils/json.py | 20 | no | medium |
| stores/redis.py | 12 | no | high |
| db/queries.py | 8 | partial | high |

---

## Findings

### P0 - Critical

| ID | Location | Issue | Recommendation | Effort |
|----|----------|-------|----------------|--------|
| AI-001 | extraction/filter/llm_classifier.py:74-76 | Prompt injection: claim fields inserted via `.format()` without sanitization | Wrap fields in XML tags; instruct model to treat as data-only | S |
| AI-002 | extraction/service.py:91-93 | Prompt injection: raw document content in extraction prompt; `{...}` causes KeyError or injection | Escape braces or use `template.replace('{content}', content)` | S |
| AI-003 | clustering/service.py:315-317 | Same injection vector in clustering summaries | Escape user content before `.format()` | S |
| B-001 | db/queries.py:109-114, 200-206 | CREATE_MEMBER_OF matches node without silo_id; cross-silo data leak possible | Add `n.silo_id = $silo_id` to node match | S |
| B-002 | db/queries.py:101-105 | DELETE_CLUSTERS returns count after DETACH DELETE (always 0) | Count before deleting | S |
| B-003 | tests/fakes/fake_graph_store.py:165+ | FakeGraphStore uses `silo_id: uuid.UUID` but protocol uses `str` | Fix type annotations to match protocol | S |
| B-004 | stores/memgraph.py:183 | Unreachable `return None` after retry loop; silent failure if tenacity changes | Replace with explicit raise | S |
| E-001 | services/context.py:187-212 | Memgraph write succeeds, Qdrant fails -> permanent desync; node invisible to search | Catch exception, delete Memgraph node or enqueue repair | M |
| P-001 | custodian/sensors/consensus.py:68-72 | N+1: up to 1000 individual get_heat() queries per sensor tick | Use GET_SEED_HEAT_BATCH for single batched query | S |
| P-002 | clustering/service.py:248-282 | N+1: PART_OF edges written one at a time; BATCH_CREATE_PART_OF exists but unused | Use batch query | S |
| S-001 | api/app.py:147-183 | MCPAuthMiddleware never mounted; per-tool auth is only enforcement | Mount middleware or add integration test for auth coverage | M |
| S-002 | config/settings.py:474-479 | Dead auth_dev_mode setting with hardcoded 'ck_dev_test' in description | Remove or implement with production guard | S |
| S-003 | config/settings.py:498, 220 | 0.0.0.0 bind + docs exposed on non-production | Disable docs in staging; default to 127.0.0.1 | S |

### P1 - High

| ID | Location | Issue | Recommendation | Effort |
|----|----------|-------|----------------|--------|
| AI-004 | llm/vertex_gemini.py:147 | datetime.utcnow() deprecated in 3.12 | Use datetime.now(UTC) | S |
| AI-005 | llm/concurrency.py:13-24 | Global semaphore tied to first event loop; breaks in multi-loop tests | Reinitialize per loop or reset in teardown | S |
| AI-006 | llm/anthropic.py:46-51 | Empty API key silently accepted at construction | Raise ValueError if key empty | S |
| AI-007 | llm/gemini.py:79-85 | Gemini lacks rate-limit retry (429/5xx) unlike other providers | Add backoff matching Anthropic pattern | M |
| AI-008 | llm/vertex_gemini.py:124-130 | Hardcoded 30s timeout overrides caller's 90s for extraction | Remove client timeout; use per-request only | S |
| E-002 | services/context.py:149-159 | Idempotency race: 50ms sleep insufficient; duplicate nodes created | Retry GET with backoff before falling through | S |
| E-003 | services/context.py:874 | get_reflections() bypasses protocol; crashes on non-MemgraphClient | Use execute_query | S |
| E-004 | pipelines/resources.py:37 | f.result() has no timeout; process hangs on teardown | Add 30s timeout | S |
| E-005 | services/context.py:131-132 | Corrupted cache entry crashes store() with ValueError | Catch ValueError, treat as cache miss | S |
| L-001 | custodian/supersession.py:290 | Auto-reflection fires on dropped pairs, not just written edges | Track written pairs; iterate only those | M |
| L-002 | mcp/tools/context_graph.py:54 | PREVENTS in causal list but not in RelationshipType enum | Add to enum or remove from list | S |
| P-003 | pipelines/assets/embedding.py:84-87 | Single-pass: only 100 nodes per run; backlog grows unbounded | Add while loop to drain queue | S |
| P-004 | pipelines/assets/extraction.py:56-58 | Single-pass: only 50 docs per run | Same fix as P-003 | S |
| P-005 | db/indexes.py:147-164 | 31 CREATE INDEX statements each open new session | Reuse single session for loop | S |
| P-006 | pipelines/assets/heat.py:51-59 | _RECOMPUTE_TIERS_CYPHER does full unlabeled node scan | Compute tier inline in _APPLY_HEAT_CYPHER | S |
| P-007 | clustering/service.py:284-346 | N+1 summary writes after asyncio.gather | Batch update after gather completes | M |
| S-004 | db/queries.py:42-62, 312-333 | Cypher rel_type builders accept raw string; injection if bypassed | Accept only RelationshipType enum | S |
| S-005 | engine/queries.py:606-616 | printf-style depth interpolation into Cypher | Build as function with isinstance(int) guard | S |
| S-006 | extraction/filter/wikidata.py:50-61 | Incomplete SPARQL escape; bidi-override/backslash-u injection | Use SPARQL library with parameterized binding | M |
| S-007 | llm/*.py | PII in error logs: all 4 clients log raw response.text | Truncate to 200 chars | S |

### P2 - Medium

| ID | Location | Issue | Effort |
|----|----------|-------|--------|
| A-001 | mcp/server.py:170 | Hardcoded tools=14 but 15 registered | S |
| A-002 | embeddings/vertex.py:126 | asyncio.get_event_loop() deprecated | S |
| A-003 | pipelines/assets/*.py | asyncio.run without loop guard | M |
| A-004 | pipelines/assets/*.py | 6 assets bypass engine/protocols.py (rule 8) | M |
| AI-009 | extraction/prompts.py:44-49 | Module-level prompt constants bypass preset logic | S |
| AI-010 | extraction/filter/llm_classifier.py:85 | Misleading comment about Exception catch | S |
| AI-011 | embeddings/jina.py:201 | Bare KeyError on missing embedding | S |
| AI-012 | llm/anthropic.py:149 | max_tokens=4096 hardcoded; no truncation check | M |
| B-005 | engine/memgraph_store.py:77 | Bare assert stripped in -O mode | S |
| B-006 | stores/redis.py:39 | Hardcoded max_connections=50 | S |
| B-007 | engine/protocols.py | Zero test importers; fake conformance unverified | S |
| B-008 | stores/qdrant.py:75-81 | Lazy client init not thread-safe | S |
| B-009 | stores/redis.py | Zero unit test coverage | M |
| B-010 | mcp/tools/context_get.py | No unit tests; only integration | M |
| B-011 | core/settings.py | Deprecated shim past TODO deadline | S |
| D-001 | justfile:68,72 | Dagster module path wrong | S |
| D-002 | api-examples.md:431 | Missing CAUSES/CORROBORATES in context_link docs | S |
| D-003 | api-examples.md:269 | as_of documented as reserved but implemented | S |
| D-004 | api-examples.md:289-305 | Missing search_mode/metadata in response | S |
| D-006 | docs/dag-architecture.md | 5 assets missing from cadence table | M |
| E-006 | stores/memgraph.py:243 | Unreachable return [] after retry | S |
| E-007 | extraction/filter/orchestrator.py:74-75 | Silent suppress on audit flush | S |
| E-008 | extraction/filter/llm_classifier.py:85-88 | LLM failures logged at INFO not WARNING | S |
| L-003 | db/custodian_read_queries.py:145 | Rule-7 filter placement fragile | S |
| L-004 | engine/queries.py:334 | Document version SUPERSEDES missing reason | S |
| P-008 | extraction/service.py:619-647 | N+1 for CONTRADICTS edges | S |
| P-009 | db/indexes.py | Missing indexes: embedded_at, compacted, tombstoned_at | M |
| P-010 | db/queries.py:789-799 | O(n^2) temporal correlation query | M |
| S-008 | mcp/auth.py:90-119 | Dead auth bypass code | S |
| S-009 | mcp/auth.py:134 | Missing strip() on expected API key | S |
| S-010 | config/settings.py:750-754 | Hardcoded postgres credentials in default DSN | S |

### P3 - Low

| ID | Location | Issue | Effort |
|----|----------|-------|--------|
| A-005 | mcp/auth.py:41-145 | Dead MCPAuthMiddleware code | S |
| A-006 | mcp/server.py:46-55 | Cast to HyperGraphStore hides missing methods | S |
| A-007 | pipelines/schedules.py:18-31 | Rule-8 violation + missing loop guard | S |
| AI-013 | llm/anthropic.py:163 | response_text logged full (truncate) | S |
| D-005 | api-examples.md:329-341 | context_graph missing metadata field | S |
| D-007 | README.md:38 | Install command bypasses lockfile | S |
| D-008 | api-examples.md:110-111 | context_commit chain_id unreachable | S |
| E-009 | extraction/filter/wikidata.py:158 | Redundant TimeoutError in except | S |
| L-005 | mcp/tools/context_assert.py:122 | Bare except swallows promote errors | S |
| L-006 | mcp/tools/context_commit.py:28 | chain_id not exposed on public tool | S |
| L-007 | mcp/tools/context_remember.py:35-46 | silo_id validated then discarded | M |
| P-011 | stores/qdrant.py:75-81 | Lazy init race (same as B-008) | S |
| P-012 | stores/redis.py:37-43 | Hardcoded max_connections | S |
| S-011 | mcp/tools/silo.py:19-52 | Unbounded dissolvability float | S |

---

## Recommended Fix Order

1. **Immediate (before any partner demos)**:
   - AI-001/002/003: Prompt injection (security + correctness)
   - B-001: Cross-silo data leak
   - E-001: Qdrant/Memgraph desync

2. **This week**:
   - P-001/002: N+1 hot loops (perf collapse at scale)
   - P-003/004: Asset truncation (backlog growth)
   - S-001/002/003: Auth gaps

3. **Before production**:
   - All remaining P1s
   - B-003 (test fidelity)
   - S-004/005/006 (injection vectors)
