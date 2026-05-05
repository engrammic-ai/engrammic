# Codebase Review - 2026-05-05

**Mode**: full
**Branch**: main  **Base**: main
**Plan**: none active
**Previous review**: 2026-05-03 (78 findings: 13 P0, 20 P1, 31 P2, 14 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

Progress since May 3rd: 8/10 P0 items fixed. The prompt injection fixes (AI-001/002/003) via `escape_for_prompt()` are verified working. However, **B-001 (silo leak in CREATE_MEMBER_OF) remains partially fixed** and **S-003 (0.0.0.0 bind) regressed**. New issues surfaced include extensive N+1 hot loops in context.py and write_path.py, plus significant dead code accumulation (122 unused config settings, 41 unused queries).

| Category | P0 | P1 | P2 | P3 | Total |
|----------|----|----|----|----|-------|
| Regression | 1 | 1 | 0 | 0 | 2 |
| Performance | 3 | 5 | 3 | 0 | 11 |
| Error Handling | 2 | 5 | 5 | 0 | 12 |
| AI/LLM | 0 | 2 | 7 | 2 | 11 |
| Dead Code | 0 | 0 | 3 | 4 | 7 |
| Blast Radius | 0 | 0 | 5 | 0 | 5 |
| **Total** | **6** | **13** | **23** | **6** | **48** |

## Themes

1. **N+1 hot loops in context.py** (P-001 to P-005) - P0/P1. Edge creation for evidence, beliefs, reflections done one-at-a-time in loops. Will collapse at scale.

2. **N+1 in custodian write_path** (P-006, P-007) - P0. CITES and PROPOSED_EDGE written individually inside transaction loop.

3. **Dead code accumulation** (D-001 to D-007) - P2/P3. 122 unused config settings, 41 unused DB queries, 3 unused classes. Tech debt drag.

4. **Error handling gaps in stores** (E-001 to E-006) - P1/P2. Silent failures on retry exhaustion, missing retries on external APIs, race conditions.

5. **AI/LLM input validation weak** (AI-001 to AI-004) - P1/P2. No content length limits, unbounded relationship counts, token costs untracked.

## Regression Status

| ID | Status | Evidence |
|----|--------|----------|
| AI-001 | FIXED | `escape_for_prompt()` at llm_classifier.py:76-78 |
| AI-002 | FIXED | `escape_for_prompt()` at extraction/service.py:96 |
| AI-003 | FIXED | `escape_for_prompt()` at clustering/service.py:362 |
| B-001 | PARTIAL | BATCH_CREATE_MEMBER_OF has silo_id, but CREATE_MEMBER_OF (line 129) does not |
| B-002 | FIXED | BATCH_CREATE_MEMBER_OF returns proper count |
| E-001 | FIXED | Memgraph/Qdrant sync with rollback at context.py:324-328 |
| P-001 | FIXED | GET_SEED_HEAT_BATCH at consensus.py:73-76 |
| P-002 | FIXED | BATCH_CREATE_PART_OF at clustering/service.py:314-321 |
| S-001 | FIXED | Auth via get_mcp_auth_context per-tool |
| S-003 | REGRESSED | 0.0.0.0 bind still at settings.py:219; docs still exposed in non-prod |

## Blast Radius Hotspots

| File | Importers | Has Tests | Risk |
|------|-----------|-----------|------|
| config/settings.py | 49 | Yes | Medium |
| engine/patterns.py | 38 | Yes | Medium |
| llm/base.py | 15 | Yes | Medium |
| custodian/models.py | 11 | Yes | Medium |
| mcp/server.py | 11 | Yes | Medium |

---

## Findings

### P0 - Critical

| ID | Location | Issue | Fix | Effort |
|----|----------|-------|-----|--------|
| P-001 | services/context.py:827-836 | N+1: assert_claim creates one execute_write per evidence edge | Batch DERIVED_FROM edges with UNWIND+MERGE | S |
| P-002 | services/context.py:949-957 | N+1: commit_belief creates one execute_write per about reference | Batch ABOUT edges with UNWIND | S |
| P-003 | custodian/write_path.py:363-374 | N+1: one tx.run per citation pair | Batch CITES with UNWIND | S |
| P-004 | custodian/write_path.py:377-392 | N+1: one tx.run per proposed edge | Batch PROPOSED_EDGE with UNWIND | S |
| E-001 | stores/memgraph.py:307 | execute_write returns [] after retry exhaustion, masking failure | Raise MemgraphOperationError | S |
| R-001 | db/queries.py:129 | CREATE_MEMBER_OF missing silo_id constraint (partial regression) | Add n.silo_id = $silo_id | S |

### P1 - High

| ID | Location | Issue | Fix | Effort |
|----|----------|-------|-----|--------|
| P-005 | services/context.py:1013-1019 | N+1: reflect() awaits tx.run per target | Batch ABOUT edges | S |
| P-006 | services/context.py:858-868 | Sequential queries in promote_claim_to_fact (2 round-trips) | Combine into single query | S |
| P-007 | services/context.py:625-639 | Sequential queries for history lookup | Combine with UNION | S |
| P-008 | services/context.py:585-592 | Sequential queries for provenance (2 round-trips) | Combine chain+root queries | S |
| P-009 | services/context.py:475-487 | Cache miss causes individual cache.set per node | Use mset for batch | S |
| E-002 | engine/qdrant_store.py:155-158 | Qdrant upsert has no try-catch | Wrap in exception handler | S |
| E-003 | services/evidence.py:87-109 | _validate_uri has no retry on transient failures | Add exponential backoff | M |
| E-004 | services/context.py:155-165 | Race condition in idempotency check | Add lock or use MERGE | M |
| E-005 | engine/auto_reflection.py:100-123 | Bare except returns None, hides error type | Return (result, error) tuple | S |
| AI-001 | extraction/service.py:84 | No content length validation before LLM | Add max_size check | S |
| AI-002 | extraction/service.py:122-182 | Entity names from LLM not validated | Validate against schema | M |
| R-002 | config/settings.py:219 | 0.0.0.0 bind (regression) | Default to 127.0.0.1 | S |
| R-003 | api/app.py:221 | Docs exposed in non-prod (regression) | Disable in staging | S |

### P2 - Medium

| ID | Location | Issue | Fix | Effort |
|----|----------|-------|-----|--------|
| E-006 | engine/qdrant_store.py:88-107 | No cleanup if create_payload_index fails after collection | Add rollback | M |
| E-007 | engine/qdrant_store.py:141-144 | Bare except in ensure_collection | Catch specific exceptions | S |
| E-008 | engine/postgres_store.py:22-82 | Partial batch failures not detected | Validate rowcount | M |
| E-009 | stores/memgraph.py:104-121 | begin_transaction not retried | Add retry wrapper | S |
| E-010 | stores/memgraph.py:111-117 | Pool exhaustion doesn't reset driver | Close driver on timeout | S |
| AI-003 | extraction/service.py:735 | Exception stored in job.error without sanitization | Use truncate() | S |
| AI-004 | extraction/service.py:108 | Full exception in logs | Use truncate() | S |
| AI-005 | llm/base.py:72-101 | No token/cost tracking | Add usage aggregation | M |
| AI-006 | clustering/service.py:346-351 | Content length not validated for total prompt size | Validate total | S |
| AI-007 | extraction/filter/llm_classifier.py:99-107 | Weak LLM output parsing | Use regex | S |
| AI-008 | extraction/service.py:122-182 | No limit on relationship count from LLM | Add max count | S |
| D-001 | db/queries.py | 30 unused query constants | Remove or document as planned | M |
| D-002 | db/custodian_queries.py | 9 unused query constants | Remove or document | S |
| D-003 | db/custodian_read_queries.py | 5 unused query constants | Remove or document | S |

### P3 - Low

| ID | Location | Issue | Fix | Effort |
|----|----------|-------|-----|--------|
| AI-009 | llm/base.py:94-105 | No schema validation before extraction | Add basic validation | S |
| AI-010 | llm/concurrency.py | Verify llm_max_concurrency is reasonable | Document safe range | S |
| D-004 | custodian/supersession.py:78 | filter_cyclic_pairs never called | Remove or wire | S |
| D-005 | clustering/models.py:118 | ClusterMembership class unused | Remove | S |
| D-006 | services/models.py:84-95 | GraphNode, GraphEdge classes unused | Remove | S |
| D-007 | config/settings.py | 122 unused config settings | Audit and prune | L |

---

## Dead Code Summary

| Type | Count | Location | Action |
|------|-------|----------|--------|
| Unused config settings | 122 | config/settings.py | Audit; remove obsolete |
| Unused DB queries | 44 | db/*.py | Remove if no planned use |
| Unused classes | 3 | models.py files | Remove |
| Unused functions | 1 | supersession.py | Remove or wire |
| Unused imports | 2+ | deps.py, agents.py | Remove |

---

## Recommended Priority

1. **P0 N+1 loops** (P-001 to P-004) - Will cause perf collapse at scale. Effort: 4x S = 1-2 hours total.
2. **P0 silent failure** (E-001) - Masks operational errors. 15 min fix.
3. **P0 silo leak** (R-001) - Security regression. 15 min fix.
4. **P1 regressions** (R-002, R-003) - 0.0.0.0 bind and docs exposure. 30 min.
5. **P1 remaining N+1** (P-005 to P-009) - Sequential queries. 2 hours.
6. **P2 dead code** (D-001 to D-003) - Tech debt cleanup. 1-2 hours.
