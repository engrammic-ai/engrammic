# Codebase Review - 2026-05-22

**Mode**: full
**Branch**: main  **Base**: main
**Plan**: none active
**Previous review**: 2026-05-08 (65 findings: 3 P0, 16 P1, 27 P2, 19 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

**Regressions from May 8 review: ALL FIXED**
- S-001 (Cypher injection): Fixed via parameterized binding + Literal validation
- L-001 (Auto-promote threshold): Fixed, raised from 1 to 3
- L-002 (Crystallize bypass): Fixed, now routes through Wisdom layer

**New critical issues:**
- **P0**: Dev auth bypass if `AUTH_ENABLED` not set in production (S-003)
- **P1**: Prompt injection in custodian identity agents - fact content unsanitized
- **P1**: Missing `UsageLimits` on identity agents - unbounded token consumption
- **P1**: No retry on Qdrant transient failures (5 locations)
- **P1**: Redis lock silently falls open on unavailability

| Category | P0 | P1 | P2 | P3 | Resolved |
|----------|----|----|----|----|----------|
| Security | 1 | 2 | 5 | 2 | 1 |
| Logic/Spec | 0 | 2 | 4 | 0 | 2 |
| Performance | 0 | 0 | 10 | 2 | 2 |
| Error Handling | 0 | 4 | 12 | 2 | 0 |
| AI/LLM | 0 | 3 | 3 | 2 | 0 |
| Blast Radius | 0 | 1 | 0 | 0 | 0 |
| **Total** | **1** | **12** | **34** | **8** | **5** |

## Themes

1. **Prompt injection in custodian identity agents** - `CustodianIdentity` and `SynthesizerIdentity` interpolate DB-controlled fact content without `escape_for_prompt()`, unlike main custodian agents.
2. **Missing resilience patterns** - Qdrant operations lack retry logic; Redis lock falls open on unavailability; Memgraph writes lack transaction error handling.
3. **Auth bypass risk** - Dev mode can be accidentally enabled in production; X-Org-Id header override breaks tenant isolation.
4. **Test coverage gap on protocols** - `engine/protocols.py` has 52 importers with only 5.8% test coverage.
5. **N+1 patterns in retention service** - Tombstone and erasure operations have per-item DB calls.

## Blast Radius Hotspots

| File | Importers | Risk | Test Coverage |
|------|-----------|------|---------------|
| `config/settings.py` | 105 direct | MEDIUM | 32.4% (adequate) |
| `engine/protocols.py` | 52 direct | **HIGH** | 5.8% (critical gap) |
| `utils/json.py` | 20 direct | LOW | Deep unit tests |

## Regression Status (from May 8)

| ID | Status | Evidence |
|----|--------|----------|
| S-001 (Cypher injection) | **FIXED** | `tombstone.py:50-52` uses `$edge_type` param binding; `Literal` validation on `TombstoneRequest` |
| L-001 (Auto-promote threshold) | **FIXED** | `_R1_THRESHOLD=3` at `context_store.py:198`; requires 3 evidence pieces |
| L-002 (Crystallize bypass) | **FIXED** | `context_store.py:443,739` routes through `commit_belief()` (Wisdom layer) |
| P-002 (O(N*depth) causal) | **FIXED** | BFS with batched queries and UNWIND, not recursive |

---

## Findings

### Security

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| S-003 | P0 | `api/auth_dep.py:26-35` | Dev auth bypass in production - `auth_enabled=false` defaults to dev context; if `AUTH_ENABLED=true` not set, all requests bypass auth | Add boot-time assertion in `get_settings()` to enforce `AUTH_ENABLED=true` when `is_production=true` | S |
| S-007 | P1 | `mcp/server.py:315` | X-Org-Id header override in dev mode - unauthenticated header can override org context, breaking tenant isolation | Only allow override when both `auth_enabled=false` AND NOT `is_production`; remove header override entirely | S |
| S-001b | P1 | `engine/tombstone.py:23` | Cypher injection structurally fragile - `.format()` pattern remains; safe due to enum validation but brittle | Apply enum validation at `build_find_query()` entry point for defense-in-depth | S |
| S-004 | P2 | `mcp/tools/context_graph.py:44` | Silo_id validation gap - validation occurs AFTER initial assignment | Add early return if `silo_id != expected_silo_id` with 403 | S |
| S-005 | P2 | `config/settings.py:256` | DSN password in connection string - if logged/serialized, password exposed | Never log DSN; use `urllib.parse.quote_plus()` for escaping | S |
| S-006 | P3 | `config/settings.py:231` | Hardcoded "context" Postgres password default | Remove hardcoded default; require explicit env var | S |
| S-008 | P2 | `db/queries.py:931` | Cypher literal substitution pattern - `.format(min_hops=..., max_hops=...)` safe now but fragile | Extract as constants with strict bounds check; add comment | S |
| S-009 | P2 | `api/routes/admin.py` | Admin endpoint missing request body size limit - unbounded `edge_ids` list | Add `max_items=10000` constraint to `edge_ids` field | S |
| S-010 | P3 | `db/postgres.py` | DSN credential in error messages - SQLAlchemy errors may leak credentials | Add custom exception handler that sanitizes credentials | S |

### Logic & Spec Conformance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| L-003 | P1 | `mcp/tools/believe.py:58-80` | believe() bypasses hypothesize->commit pipeline - creates Commitment directly, skipping WorkingHypothesis flow | Document as intentional shortcut OR route through hypothesize | M |
| L-004 | P1 | `mcp/tools/context_store.py:187` | Meta-observation layer unclear - spec says metacognition is cross-cutting; implementation treats "meta" as 5th layer | Clarify in spec that meta is a node type, not a cognitive layer | S |
| L-005 | P2 | Spec vs impl | Layer count discrepancy - spec defines 4 layers (KMWI), implementation has 6 (KMWI + meta + belief) | Update spec to document WorkingHypothesis as temporary belief state | S |
| L-006 | P2 | `context/specs/mcp-tool-surface.md` | Spec lists 14 tools, implementation has 12 consolidated tools | Update spec to match implementation | S |
| L-007 | P2 | `mcp/tools/context_crystallize.py` | context_crystallize exposed but should be internal-only per spec | Remove from external registration | S |
| L-008 | P2 | `mcp/tools/context_store.py:198` | Auto-promote checks evidence count, not multi-agent consensus per T5 spec | Enhance to verify K chains from J distinct agents, not just count | M |

### Performance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| P-001 | P2 | `retention/service.py:89-101` | N+1 tombstone queries - per-node `execute_query(TOMBSTONE_NODE)` in loop | Batch all node IDs in single UNWIND query | S |
| P-002 | P2 | `retention/erasure_service.py:64-73` | N+1 cascade referencing - per-node cascading reference lookup | Batch lookup: `UNWIND $node_ids` with multi-match | S |
| P-003 | P2 | `retention/service.py:176-179` | N+1 hard delete loop - sequential `hard_delete_node()` calls | Batch delete: single Memgraph UNWIND, parallel Qdrant | M |
| P-004 | P2 | `engine/epistemic_store.py:139-147` | Sequential belief staling - per-source `execute_write(MARK_BELIEF_STALE)` | Batch write: `UNWIND $belief_ids` | S |
| P-005 | P2 | `engine/synthesis.py:376-384` | Sequential synthesis edge creation | Batch: `UNWIND $belief_ids` | S |
| P-006 | P2 | `mcp/tools/context_admin.py:125-137` | Sequential chain reference creation | Batch: `UNWIND $ref_chain_ids` | S |
| P-007 | P2 | `custodian/identities/validator.py:63-68` | N+1 hypothesis premise lookup | Batch: `UNWIND $hypothesis_ids` | S |
| P-008 | P2 | `custodian/identities/synthesizer.py:127-136` | N+1 cluster fact fetches | Batch: pre-load all facts with `UNWIND $cluster_ids` | M |
| P-009 | P2 | `engine/tombstone.py:128-137` | Sequential edge tombstoning | Batch: `UNWIND $edge_ids` then batch invalidation | M |
| P-010 | P2 | `engine/memgraph_store.py:1229-1231` | Sequential index creation on startup | `asyncio.gather(*[...])` for parallel execution | S |
| P-011 | P3 | `services/context.py:659-678` | Cache coherency has O(N) zip loop | Pre-filter empty results (minor) | S |
| P-012 | P3 | `mcp/tools/context_get.py:150-161` | Reflection query per node | Batch query variant if >10 nodes | S |

### Error Handling & Resilience

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| E-001 | P1 | `engine/chain_applicability.py:81-94` | Unhandled Qdrant query_points failure - network/timeout propagates unhandled | Wrap in try-except; return `[]` with warning log | S |
| E-002 | P1 | `engine/qdrant_store.py:205-207,262-270,329-386` | No retry on transient Qdrant failures (5 locations) | Implement exponential backoff retry decorator (3 retries, 100ms-1s) | M |
| E-003 | P1 | `engine/synthesis.py:164-175` | No transaction error handling in batch Memgraph writes - partial failures leave inconsistent state | Wrap entire sequence in single try-except | S |
| E-004 | P1 | `engine/memgraph_store.py:444-467` | Redis lock race condition - silently fails and falls open on unavailability | Implement exponential backoff for lock attempts; add telemetry | M |
| E-005 | P2 | `engine/chain_applicability.py:77-79` | Silent Qdrant collection check failure - returns `[]` on any exception | Log collection availability errors separately | S |
| E-006 | P2 | `engine/llm_patterns.py:190-192` | Missing bounds validation on LLM timeouts | Add `timeout_s = max(1, min(timeout_s, 30))` | S |
| E-007 | P2 | `embeddings/litellm_embeddings.py:112-116` | Silent embedding cache misses with None pollution | Replace AssertionError with structured exception | S |
| E-008 | P2 | `engine/compaction.py:211-214` | Unhandled asyncio.gather failure - single exception cancels batch | Change to `return_exceptions=True`; retry failed items | S |
| E-009 | P2 | `embeddings/litellm_embeddings.py:78-91` | Missing bounds on embedding batch size - unbounded could OOM | Add max batch size constant (100); chunk texts | S |
| E-010 | P2 | `engine/qdrant_store.py:389-396` | Unvalidated payload access in vector search - if payload is None, crashes | Add `if r.payload else {}` pattern | S |
| E-011 | P2 | `engine/qdrant_store.py:83-159` | Race condition in collection double-checked lock | Add try-except on creation; handle "already exists" | S |
| E-012 | P2 | `embeddings/litellm_embeddings.py:154-170` | LiteLLM embedding timeout no retry | Add retry loop with exponential backoff | S |
| E-013 | P2 | `engine/chain_applicability.py:97-105,156-176` | Return [] on all DB errors (3 instances) - permits overpermissive fallback | Log exception details; add telemetry counter | S |
| E-014 | P2 | `engine/chain_applicability.py:122-138,347` | Missing null/type validation on session embeddings and evidence sets | Validate before operations | S |
| E-015 | P3 | `engine/patterns.py:164-169` | Pattern detection returns [] without error context | Raise ValueError for unknown pattern type | S |
| E-016 | P3 | `engine/chain_applicability.py:189-229` | Chain delivery logging swallows DB errors | Log exception stack traces; add alerting | S |

### AI/LLM

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| AI-001 | P1 | `custodian/identities/custodian.py:107-112` | Prompt injection in contradiction detection - fact content directly interpolated | Wrap in `escape_for_prompt()` before interpolation | S |
| AI-002 | P1 | `custodian/identities/synthesizer.py:141-144` | Prompt injection in synthesis identity - cluster fact content unsanitized | Wrap `f['content']` in `escape_for_prompt()` | S |
| AI-003 | P1 | `custodian/identities/custodian.py:115-118`, `synthesizer.py:147-150` | Missing UsageLimits on identity agents - unbounded token consumption | Add `usage_limits=UsageLimits(output_tokens_limit=512, request_limit=1)` | S |
| AI-004 | P2 | `custodian/identities/synthesizer.py:141-144` | Unbounded fact content in prompts - no truncation | Truncate to 200-300 chars (pattern in `llm_patterns.py:149`) | S |
| AI-005 | P2 | `custodian/proposal_worker.py:116-119` | Unbounded input to proposal synthesis | Limit fact count (max 10) and truncate each to 150 chars | S |
| AI-006 | P3 | `custodian/identities/synthesizer.py:147-150` | Missing retry envelope on synthesis calls | Wrap in `_llm_retry` decorator | S |
| AI-007 | P3 | `custodian/silo_synthesis.py:148` | No output truncation warnings | Log warning when `finish_reason == "length"` | S |

### Blast Radius

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| BR-001 | P1 | `engine/protocols.py` | Critical test coverage gap - 52 importers with only 3 test files (5.8%) | Add implementation tests for HyperGraphStore across all backends | L |

---

## Architecture Strengths

1. **Protocol-driven design**: All callers depend on `HyperGraphStore`/`EpistemicStore` protocols, not concrete implementations
2. **Consistent circuit breaker**: All Memgraph/Qdrant access wrapped with CircuitBreaker (failure_threshold=5, window_s=60)
3. **100% type coverage**: All public APIs fully typed (protocols, routes, MCP tools)
4. **LLM pattern safety**: `llm_patterns.py` properly truncates facts, validates schemas, applies confidence thresholds

## Quick Wins (Effort S, High Impact)

1. **S-003**: Add boot-time auth assertion - prevents dev bypass in production
2. **AI-001/AI-002**: Add `escape_for_prompt()` calls to identity agents
3. **AI-003**: Add `UsageLimits` to identity agent.run() calls
4. **E-002**: Implement Qdrant retry decorator (reusable across 5 locations)
5. **P-001/P-002**: Batch retention service queries
