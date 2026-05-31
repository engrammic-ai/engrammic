# Codebase Review - 2026-05-31

**Mode**: full
**Branch**: main  **HEAD**: 224f9fd (style: apply ruff format repo-wide)
**Previous review**: 2026-05-29 (4 STILL_OPEN P1s, 3 P2s)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

| Category | P0 | P1 | P2 | P3 | FP-Suppressed |
|----------|----|----|----|----|---------------|
| Carried-forward | 0 | 2 | 3 | 0 | 0 |
| Error Handling | 0 | 3 | 5 | 1 | 0 |
| AI/LLM | 0 | 2 | 4 | 2 | 0 |
| Performance | 0 | 1 | 3 | 1 | 0 |
| Blast Radius | 0 | 2 | 2 | 0 | 0 |
| Documentation | 0 | 0 | 3 | 0 | 0 |
| **Total** | **0** | **10** | **20** | **4** | **0** |

## Verdict

Production-ready with bounded, known risks. The security posture improved (1 fix since May 29), but prompt injection gaps remain the top priority. New this review: a cross-silo evidence leak pattern (P1), unbounded MCP parameters (P1), and a second prompt injection site in belief synthesis.

The carried-forward prompt injection (INJ-1) and a newly discovered one (INJ-2) are the only issues that gate sensitive-data scale. Everything else is operational hygiene.

## Themes

1. **Prompt injection gaps** - 2 findings (P1). `escape_for_prompt()` exists but is not applied consistently. custodian/visit.py and engine/synthesis.py interpolate DB content unsanitized.

2. **Missing input validation at MCP boundary** - 2 findings (P1). `top_k` and `depth` params pass through unbounded. Agent can OOM the service or blow query latency.

3. **Permissive error fallbacks** - 3 findings (P1-P2). Auth DB errors swallowed, cross-silo evidence leaked on query errors, marker index failures silent.

4. **Missing timeouts and retries** - 4 findings (P2). No asyncio timeout on Memgraph execute, no retry on WorkOS/Qdrant, pydantic-ai agents bypass retry layer.

5. **High-import modules without tests** - 4 findings (P1-P2). `config.logging` (41 imports), `pipelines.partitions` (28), `services.models` (16), `pipelines.resources` (19) have no dedicated unit tests.

6. **LLM cost/token controls weak** - 2 findings (P2). Extraction uses char limits not tokens, no per-run cost ceiling.

## Blast Radius Hotspots

| Module | Import Count | Has Tests | On Hot Path | Risk Level |
|--------|-------------|-----------|-------------|------------|
| `config.settings` | 46 | Partial | Yes | HIGH |
| `config.logging` | 41 | No | Yes | HIGH |
| `pipelines.partitions` | 28 | No | No | MEDIUM |
| `services.models` | 16 | Indirect | Yes | HIGH |
| `pipelines.resources` | 19 | No | No | MEDIUM |

## Regression Status (from May 29)

| ID | Status | Evidence |
|----|--------|----------|
| INJ-1 (P1) Custodian prompt injection | STILL_OPEN | `custodian/identities/custodian.py:108-111` |
| S-003 (P1) Dev-auth bypass | STILL_OPEN | `api/auth_dep.py:26-35` |
| AI-003 (P2) `max_length=500` on reasoning | STILL_OPEN | `custodian/identities/custodian.py:31` |
| AI-001 (P2) `tool_calls_limit` removed | **FIXED** | `custodian/agents.py:169-182` |
| L-002/L-003 (P2) `silo_id=None` in metrics | STILL_OPEN | `mcp/tools/believe.py:48`, `mcp/tools/learn.py:71,73` |
| A-001 (P1) OTLP firewall rule | CANT_VERIFY | Infra config not in repo |
| A-007 (P3) `embedding_cache_miss` counter | STILL_OPEN | `cache/embedding_cache.py:39` |

## Plan Status (Pending Work)

| Plan | Status | Note |
|------|--------|------|
| Self-serve org provisioning | **SHIPPED** | PR #55 merged; README stale |
| Join Engrammic onboarding | Ready | Blocker satisfied; can execute |
| Evidence verification | Ready | Prerequisites: Nango account + integrations |
| Self-hosted REST API Phase 1 | Ready | Deferred |

---

## Findings

### Category: Carried-forward

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| INJ-1 | P1 | `custodian/identities/custodian.py:108-111` | Raw DB fact content interpolated into LLM synthesis prompts, no sanitization | Apply `escape_for_prompt()` from `llm/sanitize.py` | S |
| S-003 | P1 | `api/auth_dep.py:26-35` | Dev `AuthContext` returned when `AUTH_ENABLED` unset, no code-level environment guard | Add `ENV != production` check or fail closed | S |
| AI-003 | P2 | `custodian/identities/custodian.py:31` | `reasoning: str` has no `max_length` constraint | Add `max_length=500` to field | S |
| L-002 | P2 | `mcp/tools/believe.py:48` | `silo_id=None` passed to metrics | Thread `auth.silo_id` through | S |
| L-003 | P2 | `mcp/tools/learn.py:71,73` | `silo_id=None` passed to metrics | Thread `auth.silo_id` through | S |

### Category: Error Handling

| ID | Priority | Location | Issue | Failure Mode | Fix | Effort |
|----|----------|----------|-------|--------------|-----|--------|
| ERR-1 | P1 | `auth/workos_client.py:94` | Silent auth DB failure on every request | `user_upsert_failed` swallows all DB errors, returns `db_user_id=None`; usage tracking silently drops | Distinguish transient/permanent; emit metric on swallow | M |
| ERR-2 | P1 | `mcp/tools/recall.py:40-57` | `top_k` unbounded | Agent can pass `top_k=10000`, OOM or stall query pipeline | `effective_top_k = min(effective_top_k, 100)` | S |
| ERR-3 | P1 | `engine/chain_applicability.py:174-177` | Permissive fallback leaks cross-silo evidence | On Memgraph error, returns all silo-wide evidence (up to 1000 nodes) | Fail closed, return empty set | S |
| ERR-4 | P2 | `auth/workos_client.py:46-52` | WorkOS auth no retry | Single transient 5xx rejects auth entirely | 2-attempt retry with backoff | S |
| ERR-5 | P2 | `engine/qdrant_store.py:200-207` | Qdrant upsert no retry | `ConnectionError` re-raises immediately, write lost | 2-attempt retry on `ConnectionError` | S |
| ERR-6 | P2 | `mcp/tools/recall.py:218-254` | `depth` not validated at MCP boundary | Agent can pass `depth=99` | Clamp `depth = max(0, min(depth, 3))` | S |
| ERR-7 | P2 | `engine/markers.py:415-422` | Marker Redis index failure silent | Index failure logged/swallowed; markers not indexed | Track metric counter | S |
| ERR-8 | P2 | `engine/chain_applicability.py:210-216` | `chain_delivery_log` commit missing | `ChainDelivery` added without explicit commit | Verify context manager auto-commits or add explicit | S |
| ERR-9 | P3 | `engine/chain_applicability.py:180-188` | `_get_silo_wide_evidence` inner fallback no error handling | If Memgraph down, raises unhandled | Add try/except returning empty set | S |

### Category: AI/LLM

| ID | Priority | Location | Issue | Risk | Fix | Effort |
|----|----------|----------|-------|------|-----|--------|
| INJ-2 | P1 | `engine/synthesis.py:82` | `synthesize_belief` prompt unsanitized | Fact content from Memgraph fed to LLM without escaping | Wrap with `escape_for_prompt()` | S |
| INJ-3 | P1 | `custodian/visit.py:163,167` | Visit prompts unsanitized | `naive_summary` and `child_finding_summaries` interpolated raw | Apply `escape_for_prompt()` | S |
| TOK-1 | P2 | `extraction/service.py:95` | Extraction size limit char-based not token-based | 100k chars could be 40k+ tokens | Add token estimate check | M |
| TOK-2 | P2 | `pipelines/assets/extraction.py` | No per-run cost ceiling | 500 docs × 25k tokens = unbounded LLM bills | Add `max_tokens_per_run` budget counter | M |
| REL-1 | P2 | `custodian/visit.py` | pydantic-ai agents no retry on rate limits | 429 kills entire visit | Wrap `agent.run()` with tenacity retry | M |
| OUT-1 | P2 | `extraction/service.py:137-225` | LLM output written to graph without validation | Hallucinated values become node labels | Add max-length trim and strip control chars | M |
| CACHE-1 | P3 | `llm/litellm_provider.py` | No LLM response caching | Identical prompts re-issue completions | Enable `litellm.cache` with Redis | M |
| REL-2 | P3 | `clustering/service.py:362-370` | Prompt size check only logs, doesn't truncate | Large clusters permanently skipped | Truncate contents and retry | M |

### Category: Performance

| ID | Priority | Location | Issue | SLO Impact | Fix | Effort |
|----|----------|----------|-------|------------|-----|--------|
| PERF-1 | P1 | `stores/memgraph.py` | No asyncio timeout on Memgraph execute | Slow query blocks connection 30s, cascading pool exhaustion | Wrap `session.run` in `asyncio.wait_for` (2s read / 5s write) | S |
| PERF-2 | P2 | `recall.py:190-201` | N+1 per-node MARK_NODE_ACCESSED writes | Up to 10 writes per recall saturates pool | Batch with `UNWIND $node_ids` | M |
| PERF-3 | P2 | `context.py:1620-1637` | Two sequential writes for SUPERSEDES link | Doubles link latency vs 100ms SLO | Merge into one Cypher with `WITH` | S |
| PERF-4 | P2 | `recall.py:104-127` | Engagement detection blocks recall response | Adds latency after search results ready | Move to concurrent `asyncio.gather` | M |
| PERF-5 | P3 | `context_get.py:150-162` | N+1 per-node reflections queries | 10 concurrent queries at depth=2 | Batch query `WHERE obs.about_id IN $node_ids` | M |

### Category: Blast Radius / Test Coverage

| ID | Priority | Location | Issue | Risk | Fix | Effort |
|----|----------|----------|-------|------|-----|--------|
| BR-1 | P1 | `config/logging.py` | 41 imports, no dedicated tests | Universal dependency, breakage silences logs repo-wide | Add `tests/unit/config/test_logging.py` | M |
| BR-2 | P1 | `services/models.py` | 16 imports, on hot path, indirect tests only | `derive_silo_id` gates scoping on every MCP call | Add unit tests for `ScopeContext`, `derive_silo_id` | M |
| BR-3 | P2 | `pipelines/partitions.py` | 28 imports, no tests | `silo_partitions` fan-out key for SAGE jobs | Add dedicated test | M |
| BR-4 | P2 | `pipelines/resources.py` | 19 imports, no tests | `MemgraphResource` failures only surface in full pipeline runs | Add standalone test | M |

### Category: Documentation

| ID | Priority | Location | Issue | Fix | Effort |
|----|----------|----------|-------|-----|--------|
| DOC-1 | P2 | `CLAUDE.md` | Tool table lists 13 verbs; missing `dismiss` and `tick` | Add rows for `dismiss` and `tick` | S |
| DOC-2 | P2 | `context/architecture.md` | Lists 3 Dagster jobs; code has 7 | Add orphan_recovery, telemetry_gauges, telemetry_prune, usage_retention, validator_job | S |
| DOC-3 | P2 | `context/plans/README.md` | Self-serve org provisioning shown as "Ready to execute" but shipped (PR #55) | Move to Shipped section, update onboarding plan status | S |

---

## Pick Up Next (suggested order)

1. **Prompt injection (S effort, gates sensitive-data scale)**
   - INJ-1, INJ-2, INJ-3: Apply `escape_for_prompt()` in 3 locations

2. **MCP input validation (S effort, prevents DoS)**
   - ERR-2: Clamp `top_k` to 100
   - ERR-6: Clamp `depth` to 3

3. **Cross-silo evidence leak (S effort, security)**
   - ERR-3: Fail closed on query errors in `chain_applicability.py`

4. **Memgraph timeout guard (S effort, SLO protection)**
   - PERF-1: Add `asyncio.wait_for` to execute path

5. **Doc fixes (S effort, cheap wins)**
   - DOC-1, DOC-2, DOC-3

6. **Test coverage for high-import modules (M effort, risk reduction)**
   - BR-1, BR-2: Tests for `config.logging` and `services.models`

7. **LLM reliability (M effort)**
   - REL-1: Add retry to pydantic-ai agent calls
   - ERR-4, ERR-5: Add retry to WorkOS/Qdrant

---

## Summary for User

**P0**: 0 | **P1**: 10 | **P2**: 20 | **P3**: 4

**Top 5 Issues (effort-weighted):**
1. [P1/S] `engine/synthesis.py:82`: NEW prompt injection in belief synthesis
2. [P1/S] `mcp/tools/recall.py:40-57`: Unbounded `top_k` can OOM service
3. [P1/S] `engine/chain_applicability.py:174-177`: Cross-silo evidence leak on error
4. [P1/S] `stores/memgraph.py`: Missing asyncio timeout blows all SLOs
5. [P1/S] `custodian/identities/custodian.py:108-111`: Known prompt injection still open

**Regressions**: 4 of 6 carried-forward P1/P2s remain unfixed; 1 FIXED (AI-001)

**Plans**: Self-serve org provisioning shipped but README stale; onboarding plan unblocked
