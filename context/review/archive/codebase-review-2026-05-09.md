# Codebase Review - 2026-05-09

**Mode**: branch
**Branch**: feat/skills-registry  **Base**: 04304f58
**Plan**: context/plans/2026-05-08-review-followup.md, context/plans/2026-05-08-self-hosted-telemetry.md
**Previous review**: 2026-05-08 (65 findings: 3 P0, 16 P1, 27 P2, 19 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

Previous P0 S-001 (Cypher injection) **STILL OPEN**. Both telemetry and review-followup plans are fully implemented, but the branch contains significant **scope creep**: the entire skills registry feature (routes, MCP tool, migration) is not in any plan.

Critical new issues:
- **CRITICAL**: Auth stubs (`_get_silo_id`, `_require_admin`) are no-ops - admin API is wide open
- **CRITICAL**: Global unique index on `skills.name` breaks multi-tenancy (should be `UNIQUE(name, silo_id)`)
- **HIGH**: Tool count is 10, CLAUDE.md documents 9
- **HIGH**: Protocol violation - `PostgresStore` imported directly in `context_store.py`
- **HIGH**: Prompt injection in `silo_synthesis.py` entity name fallback
- **HIGH**: No wall-clock timeout on 6 `agent.run()` call sites

| Category | P0 | P1 | P2 | P3 |
|----------|----|----|----|----|
| Security | 2 | 2 | 0 | 0 |
| Logic/Spec | 1 | 2 | 2 | 0 |
| Performance | 0 | 1 | 5 | 2 |
| Error Handling | 1 | 4 | 4 | 3 |
| AI/LLM | 0 | 3 | 3 | 2 |
| Architecture | 0 | 2 | 1 | 0 |
| Test Coverage | 0 | 2 | 2 | 0 |
| Plan Conformance | 0 | 1 | 0 | 0 |
| **Total** | **4** | **17** | **17** | **7** |

## Themes

1. **Auth stubs and multi-tenancy gaps** - 4 findings. Skills API completely unauthenticated, unique index breaks silo isolation.
2. **Prompt injection and LLM resilience** - 6 findings. Previous silo_synthesis partially fixed, entity fallback still vulnerable. No timeouts.
3. **N+1 and sequential async patterns** - 4 findings. Evidence validation, skills search, proposals fetch all serial.
4. **Test coverage gaps on new feature** - 4 findings. Zero E2E for context_skills, REST routes never HTTP-tested.
5. **Spec drift** - 3 findings. Tool count 10 vs 9, protocol violation, conditional registration.

## Blast Radius Hotspots

| File | Importers | Risk | Changes This Review |
|------|-----------|------|---------------------|
| `stores/memgraph.py` | 15 src, 40+ tests | HIGH | Modified |
| `mcp/tools/context_store.py` | 12 (incl. telemetry, metrics) | HIGH | Modified |
| `mcp/tools/context_recall.py` | 11 | MEDIUM | Modified |
| `mcp/tools/context_skills.py` | 1 | LOW | NEW |
| `api/routes/skills.py` | 2 | LOW | NEW |

## Regression Status (from May 8)

| ID | Status | Evidence |
|----|--------|----------|
| S-001 (Cypher injection) | **STILL OPEN** | `tombstone.py:44`, `admin.py:55` still interpolate strings |
| L-001 (Auto-promote threshold) | OPEN | `_R1_THRESHOLD=3` exists but enforcement not verified |
| L-002 (context_reason bypass) | OPEN | Still bypasses ProposedBelief flow |

## Plan Conformance

**review-followup.md**: All 4 items COVERED (P-002 batching, B-001/B-002/B-003 tests)

**self-hosted-telemetry.md**: All 7 items COVERED

| Change | Status | Note |
|--------|--------|------|
| `context_skills.py`, `skills.py`, skills migration | **CREEP** | Not in any plan |
| `tracing.py` | **CREEP** | OpenTelemetry tracing not scoped |
| Extra `silo_id` labels on non-MCP metrics | Partial creep | Minor, likely beneficial |

---

## Findings

### Security

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| S-001 | P0 | `engine/tombstone.py:44,51` | Cypher injection via `edge_type` and `created_before` - strings interpolated into query | Parameterize: `$edge_type`, `$created_before` | S |
| S-002 | P0 | `api/routes/skills.py:23-35` | `_get_silo_id` returns hardcoded `"default-silo"`, `_require_admin` is no-op - admin API wide open | Integrate WorkOS auth or block routes in non-dev | M |
| S-003 | P1 | `alembic/...add_skills_table.py:50` | `ix_skills_name` is `UNIQUE(name)` globally, not per-silo - breaks multi-tenancy | Change to `UNIQUE(name, silo_id)` | S |
| S-004 | P1 | `silo_synthesis.py:115-116` | Entity names joined unsanitized into `top_down_prior` before outer `escape_for_prompt` | Apply `escape_for_prompt` to each name individually | S |

### Logic/Spec

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| L-001 | P0 | `mcp/tools/__init__.py:39-42` | Registers 10 tools, CLAUDE.md documents 9 | Update CLAUDE.md or justify undocumented | S |
| L-002 | P1 | `mcp/tools/__init__.py:36-42` | `context_skills` registration conditional (`try/except pass`) - silent capability split | Fail loudly or document conditional registration | S |
| L-003 | P1 | `schemas/skill.py:48` vs `migration:33` | `source` is `Literal["builtin","user"]` but DB column allows any 20-char string | Add CHECK constraint in migration | S |
| L-004 | P2 | `mcp/tools/context_recall.py:153-164` | Graph traversal drops `as_of` param silently | Forward `as_of` to `_context_graph` | S |
| L-005 | P2 | `mcp/tools/context_update_belief.py:31-39` | `reason` field not persisted to graph | Pass to UPDATE query | S |

### Performance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| P-001 | P1 | `context_store.py:168-177` | N+1 evidence validation - sequential `validate()` per item | `asyncio.gather(*[validate(ref) for ref in evidence_list])` | S |
| P-002 | P2 | `api/routes/skills.py:103-104` | `source` filter applied post-fetch in Python | Push filter into DB query | S |
| P-003 | P2 | `services/skills.py:129` | `search` loads 10k skills then filters in Python | Add `WHERE ILIKE` clause | M |
| P-004 | P2 | `context_store.py:461` | `PostgresStore()` instantiated per request | Inject shared instance | S |
| P-005 | P2 | `context_recall.py:152,165,178,193` | `_fetch_pending_proposals` called serially after primary query | Fire concurrently with `asyncio.gather` | S |
| P-006 | P2 | `mcp/tools/context_skills.py` | No cache on list/get - hits Postgres every call | Add TTL cache (5-10s) | M |
| P-007 | P3 | `services/skills.py` (import_skill) | Blocking `socket.getaddrinfo` in SSRF guard | Wrap with `run_in_executor` | S |
| P-008 | P3 | `evidence.py:123-129` | `validate_all` exists but serial, never called | Fix to use gather, call from `_context_assert` | S |

### Error Handling

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| E-001 | P0 | `context_skills.py:94-104` | No exception handling around `_context_skills_impl` - `record_mcp_tool(success=False)` never called | Add try/except, call metric with `success=False` | S |
| E-002 | P1 | `skills.py:63-118` | No error handling in `list_skills`, `search_skills`, `get_skill` routes | Add try/except, return structured 500s | S |
| E-003 | P1 | `skills.py:143-149` | `update_skill` does not catch `ValueError` | Add handler returning 400 | S |
| E-004 | P1 | `skills.py:83-89` | `import_skill` only catches `ValueError` - network/auth errors surface as 500 | Add catch-all returning 502 | S |
| E-005 | P1 | `litellm_embeddings.py:120` | Cache merge can silently drop embeddings | Raise if `len(result) != len(texts)` | S |
| E-006 | P2 | `litellm_embeddings.py:138` | No retry on `litellm.aembedding` | Add tenacity retry for transient errors | M |
| E-007 | P2 | `litellm_embeddings.py:158` | `embed_single` raises `IndexError` on empty result | Check `if not results` before indexing | S |
| E-008 | P2 | `litellm_embeddings.py:144` | Bare `except Exception` swallows type info | Re-raise specific LiteLLM exceptions | S |
| E-009 | P2 | `tracing.py:37` | Hardcodes `insecure=True`, ignores `OTEL_EXPORTER_OTLP_INSECURE` | Read env var like metrics.py | S |
| E-010 | P3 | `tracing.py:27`, `metrics.py:29` | No guard against double-initialization | Add `_initialized` flag | S |
| E-011 | P3 | `context_skills.py:104` | `success` metric always True even on error result | Check `"error" in result` | S |
| E-012 | P3 | `litellm_provider.py:82-90,124-132` | No retry on rate-limit errors | Add tenacity retry for `RateLimitError` | M |

### AI/LLM

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| A-001 | P1 | `visit.py:535,590,684,758`, `proposal_worker.py:120`, `silo_synthesis.py:133` | No wall-clock timeout on `agent.run()` - can hang indefinitely | Wrap with `asyncio.wait_for(..., timeout=<budget>)` | M |
| A-002 | P1 | `visit.py:162,166` | `naive_summary` and `child_finding_summaries` not sanitized in prompt | Wrap with `escape_for_prompt()` | S |
| A-003 | P1 | `visit.py:221-222` | `claim.text` and `citation_ids` not sanitized in stitch prompt | Wrap with `escape_for_prompt()` | S |
| A-004 | P2 | `litellm_embeddings.py:138` | No timeout on `litellm.aembedding()` | Pass `timeout=30` | S |
| A-005 | P2 | `proposal_worker.py:120`, `silo_synthesis.py:133` | No token/cost telemetry after `agent.run()` | Emit `result.usage()` to `record_pass_cost` | S |
| A-006 | P2 | `llm/sanitize.py` | `escape_for_prompt` only escapes braces, not instruction-like text | Consider length cap + logging for injection phrases | M |
| A-007 | P3 | `litellm_provider.py` | All errors coerced to `LiteLLMError` - can't distinguish rate-limit | Preserve exception subtypes | S |
| A-008 | P3 | pydantic-ai agents | `retries=8` is validation retry, not HTTP retry | Add HTTP-level retry in provider | M |

### Architecture

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| AR-001 | P1 | `context_store.py:374` | Direct import of `PostgresStore` violates CLAUDE.md Rule 4 | Inject via service layer or `ctx_svc` | S |
| AR-002 | P1 | `mcp/tools/context_skills.py` | `context_skills` is infra/meta tool, not EAG cognitive op - conceptual boundary violation | Document as out-of-band infrastructure or remove from MCP surface | S |
| AR-003 | P2 | `services/skills.py` | No `primitives.*` imports in skills layer | Verify if schema types should come from primitives | S |

### Test Coverage

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| T-001 | P1 | `tests/e2e/test_mcp_tools.py` | Zero E2E coverage for `context_skills` | Add E2E test: register skill via REST, read via MCP | M |
| T-002 | P1 | `tests/unit/api/test_skills_routes.py` | Only router introspection - no HTTP requests | Add TestClient tests for all endpoints | M |
| T-003 | P2 | `alembic/.../add_skills_table.py` | No migration test for upgrade/downgrade | Add migration test | S |
| T-004 | P2 | `context_skills.py` | `register()` wrapper (auth, metrics) untested | Add unit test for wrapper | S |

### Plan Conformance

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| PC-001 | P1 | Branch scope | Skills feature (routes, MCP tool, migration) not in any plan | Create plan or acknowledge scope change | S |
