# Codebase Review - 2026-05-06

**Mode**: full
**Branch**: main  **Base**: main
**Plan**: none active
**Previous review**: 2026-05-05 (48 findings: 6 P0, 13 P1, 23 P2, 6 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

Good progress since May 5th: All 4 previous P0 N+1 issues (P-001 to P-004) verified FIXED. Previous security regressions R-001, R-002, R-003 all FIXED. AI/LLM findings AI-001, AI-005, AI-008 RESOLVED (content validation, token tracking, relationship limits now in place).

However, new issues surfaced:
- **CRITICAL**: Cypher injection in `tombstone.py` via `edge_type` interpolation (DEFERRED - security)
- **BREAKING**: LiteLLM consolidation left stale call sites in `embedding.py` and test files
- **HIGH**: 4 unguarded Qdrant operations in `engine/qdrant_store.py`
- **HIGH**: Entire `custodian/supersession.py` (388 lines) is dead code

| Category | P0 | P1 | P2 | P3 | Resolved | Total |
|----------|----|----|----|----|----------|-------|
| Performance | 0 | 3 | 5 | 2 | 4 | 10 |
| Error Handling | 0 | 4 | 3 | 1 | 2 | 8 |
| Security (DEFERRED) | 1 | 2 | 4 | 3 | 3 | 10 |
| AI/LLM | 0 | 0 | 4 | 2 | 3 | 6 |
| Breaking Changes | 0 | 3 | 0 | 0 | 0 | 3 |
| Dead Code | 0 | 2 | 6 | 11 | 0 | 19 |
| **Total** | **1** | **14** | **22** | **19** | **12** | **56** |

## Themes

1. **LiteLLM consolidation incomplete** - Breaking call sites in `embedding.py:118` and 7 test locations still reference removed `provider` param and `vector_size` arg.

2. **Qdrant engine layer unguarded** - `batch_upsert`, `upsert_cluster_embedding`, `query`, `delete` all lack try-catch, bypassing typed error contract.

3. **Dead code accumulation** - `custodian/supersession.py` entirely unreachable, 15+ unused DB queries, 7 unused nested config classes.

4. **N+1 in custodian write paths** - `supersession.py` and `promotion.py` still have per-item DB writes in loops (though the module is dead).

## Regression Status (from May 5)

| ID | Status | Evidence |
|----|--------|----------|
| P-001 to P-004 | FIXED | `write_path.py` uses UNWIND batches; extraction uses `BATCH_FIND_OR_CREATE_ENTITIES` |
| E-001 | FIXED | `stores/memgraph.py` raises `MemgraphOperationError` |
| E-002 | FIXED | `stores/qdrant.py:upsert` has exception handling |
| R-001 | FIXED | `CREATE_MEMBER_OF` has silo_id constraint |
| R-002 | FIXED | `settings.py` defaults to `127.0.0.1` |
| R-003 | FIXED | Docs gated on environment |
| AI-001 | FIXED | `MAX_CONTENT_SIZE = 100_000` guard in extraction |
| AI-005 | FIXED | Token/cost tracking via `_record_usage`, `compute_cost_usd` |
| AI-008 | FIXED | `MAX_RELATIONSHIPS = 500` cap enforced |

## Breaking Changes (ACTION REQUIRED)

| File | Line | Issue | Fix |
|------|------|-------|-----|
| `pipelines/assets/embedding.py` | 118 | `qdrant_store(vector_size=...)` invalid | Remove arg |
| `tests/test_embedding_asset.py` | 38 | `provider="jina"` invalid | Remove arg |
| `tests/test_dagster_resources.py` | 126,139,153,163 | `provider="jina"` invalid | Remove arg |
| `tests/test_dagster_resources.py` | 134 | Mock assertion wrong | Fix to no-arg |
| `tests/test_dagster_resources.py` | 229 | `.provider` attribute gone | Remove assertion |
| `tests/test_dagster_resources.py` | 233-248 | Test premise invalid | Delete test |

---

## Findings

### Performance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| P-005 | P1 | `custodian/supersession.py:272-354` | N+1 edge creation per supersession pair | Batch with UNWIND (module is dead - skip) | M |
| P-006 | P1 | `custodian/promotion.py:266-293` | N+1 inside tx for findings and edges | Batch with UNWIND per type | M |
| P-007 | P1 | `custodian/promotion.py:177-239` | N+1 fallback loop for min_quality filter | Filter in Cypher with IN | S |
| P-008 | P2 | `custodian/supersession.py:362-378` | Sequential auto-reflections | asyncio.gather (module dead) | S |
| P-009 | P2 | `clustering/service.py:222-254` | N+1 MEMBER_OF writes per cluster | Aggregate into single UNWIND | M |
| P-010 | P2 | `clustering/service.py:583-654` | Same N+1 in atomic variant | Same fix as P-009 | M |
| P-011 | P2 | `context.py:848-856` | Sequential split write for reason() | Merge with FOREACH | S |
| P-012 | P2 | `context.py:1066-1073` | Sequential DECLARED_BY edge | Merge with FOREACH | S |
| P-013 | P3 | `context.py:254-266` | Auto-tag causes 2nd RTT | Fold into CREATE | M |
| P-014 | P3 | `clustering/service.py:697-718` | Double query for list+count | Inline count | S |

### Error Handling

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| E-005 | P1 | `engine/qdrant_store.py:batch_upsert` | No try-catch, raw exception | Wrap with typed error | S |
| E-006 | P1 | `engine/qdrant_store.py:upsert_cluster_embedding` | No try-catch | Wrap with typed error | S |
| E-007 | P1 | `engine/qdrant_store.py:query` | No try-catch | Wrap with typed error | S |
| E-009 | P1 | `engine/qdrant_store.py:_ensure_collection` | Race in collection creation | Add asyncio.Lock | M |
| E-008 | P2 | `engine/qdrant_store.py:delete` | No try-catch, silent swallow | Wrap, log real errors | S |
| E-010 | P2 | `services/silo.py:get_or_create` | TOCTOU on silo creation | Use MERGE | S |
| E-011 | P2 | `embeddings/litellm_embeddings.py` | No retry on rate limits | Add tenacity | M |
| E-012 | P3 | `pipelines/resources.py:_close_async` | Timeout exception propagates | Wrap and log | S |

### Security (DEFERRED)

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| S-001 | CRITICAL | `engine/tombstone.py:44` | Cypher injection via edge_type | Validate against allowlist | S |
| S-002 | HIGH | `api/routes/admin.py:32` | Admin open when key unset | Require key in prod | S |
| S-003 | HIGH | `config/settings.py:131` | Hardcoded postgres password | Remove default | S |
| S-004 | MEDIUM | settings.py | max_request_body_mb unenforced | Add middleware | S |
| S-005 | MEDIUM | justfile:68 | Dagster binds 0.0.0.0 | Change to 127.0.0.1 | S |
| S-006 | MEDIUM | `mcp/tools/context_recall.py` | Skips silo ownership check | Add validation | S |
| S-007 | MEDIUM | `mcp/tools/context_recall.py` | Unbounded top_k/node_ids | Add caps | S |
| S-008 | LOW | settings.py:219 | Duplicate host config | Consolidate | M |
| S-009 | LOW | tombstone.py:46 | Float interpolated in Cypher | Parameterize | S |
| S-010 | LOW | settings.py:693 | No admin_api_key enforcement | Extend validator | S |

### AI/LLM

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| AI-002 | P2 | `custodian/supersession_parser.py:31` | Missing escape_for_prompt | Add escape | S |
| AI-003 | P2 | `embeddings/litellm_embeddings.py:135` | Unbounded batch to provider | Add batch size limit | S |
| AI-004 | P2 | `clustering/service.py:378` | Missing timeout on LLM call | Add timeout=60.0 | S |
| AI-006 | P2 | `extraction/service.py:750` | cost_usd hardcoded to 0.0 | Compute from usage | S |
| AI-007 | P3 | `llm/litellm_provider.py:115` | json_object fallback undocumented | Add debug log | S |
| AI-009 | P3 | llm/concurrency.py | Semaphore pools not coordinated | Consider priority queues | M |

### Dead Code

| ID | Priority | Location | Issue | Action | Effort |
|----|----------|----------|-------|--------|--------|
| DC-01 | P1 | `custodian/supersession.py` | Entire 388-line module dead | Delete file | S |
| DC-02 | P1 | `db/queries.py` | 8 unused query constants | Delete | S |
| DC-13 | P2 | `db/custodian_queries.py` | 6 unused functions | Delete | M |
| DC-14 | P2 | `db/custodian_queries.py` | 2 forward-plumbing constants | Delete or document | S |
| DC-15 | P2 | `config/settings.py` | 7 unused nested config classes | Remove | L |
| DC-16 | P2 | `config/settings.py` | StripeConfig dead | Delete | M |
| DC-17 | P2 | `config/settings.py` | JinaConfig, VertexConfig dead | Delete | M |
| DC-18 | P3 | `models/inference.py` | Unused model exports | Remove from __all__ | S |
| DC-19 | P3 | `core/__init__.py` | Dead re-exports | Remove | S |

---

## Recommended Priority

1. **Breaking changes** (3 items) - Runtime failures in embedding pipeline and tests. 30 min total.
2. **Qdrant error handling** (E-005 to E-009) - Untyped exceptions bypass error contract. 1-2 hours.
3. **Dead code cleanup** (DC-01, DC-02) - Delete supersession.py and unused queries. 30 min.
4. **Performance P1s** (P-006, P-007) - N+1 in promotion.py. 1-2 hours.
5. **Security** (DEFERRED) - Document for later sprint.

## Blast Radius Hotspots

| File | Importers | Has Tests | Risk |
|------|-----------|-----------|------|
| `config/settings.py` | 47 | Yes | Medium |
| `config/logging` | 33 | No | HIGH |
| `pipelines/resources.py` | 31 | Yes | CRITICAL (broken) |
| `utils/json` | 22 | No | Medium |
