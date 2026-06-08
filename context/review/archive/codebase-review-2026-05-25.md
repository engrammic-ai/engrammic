# Codebase Review - 2026-05-25

**Mode**: branch
**Branch**: feat/telemetry-observability  **Base**: 2b233ba (main)
**Plan**: context/plans/2026-05-25-telemetry-observability.md (SHIPPED)
**Previous review**: 2026-05-22 (55 findings: 1 P0, 12 P1, 34 P2, 8 P3)
**Linter baseline**: ruff clean (0 issues)

## Executive Summary

**Regressions from May 22 review:**
- S-003 (Auth bypass): NOT ADDRESSED on this branch (scope: telemetry only)
- Prompt injection in custodian identity agents: NOT ADDRESSED (pre-existing)
- Missing UsageLimits on identity agents: NOT ADDRESSED (pre-existing)

**New issues on this branch:**
- **P0**: Test failure - `tests/integration/test_mcp_protocol.py` calls `register_all(mcp, profile=...)` but signature changed
- **P1**: OTLP firewall rule missing - Cloud Run cannot reach SigNoz collector (port 4317 blocked)
- **P1**: `record_tool_error` unguarded in exception handler - OTel errors hijack tool exceptions
- **P1**: `_track_node_access` synchronous on recall hot path - adds 50-200ms for top_k=10
- **P1**: `record_supersession_skipped` called on success path, not skip path (inverted metric)

| Category | P0 | P1 | P2 | P3 | FP-Suppressed |
|----------|----|----|----|----|---------------|
| Logic/Spec | 0 | 1 | 3 | 4 | 0 |
| Performance | 0 | 1 | 1 | 2 | 0 |
| Error Handling | 0 | 2 | 2 | 0 | 0 |
| Architecture | 0 | 1 | 4 | 3 | 0 |
| Plan Conformance | 0 | 0 | 3 | 1 | 0 |
| Blast Radius | 1 | 0 | 1 | 0 | 0 |
| AI/LLM | 0 | 1 | 1 | 1 | 0 |
| **Total** | **1** | **6** | **15** | **11** | **0** |

## Themes

1. **silo_id propagation incomplete** - 5 findings. `believe.py`, `learn.py`, `middleware.py`, and `chain_applicability.py` pass `silo_id=None` while `remember.py` and `recall.py` correctly derive it. Per-silo metric attribution broken for 50% of tools.
2. **Telemetry error handling gaps** - 4 findings. Metric calls lack exception guards; if OTel fails, tool errors are masked or results discarded.
3. **Infrastructure gaps** - 2 findings. Missing firewall rule blocks OTLP traffic; missing health check on SignozHost.
4. **Test breakage from profile removal** - 1 P0. Integration tests still call `register_all` with `profile=` argument that no longer exists.

## Blast Radius Hotspots

| File | Importers | Risk | Changes This Review |
|------|-----------|------|---------------------|
| `telemetry/metrics.py` | 30 direct | LOW | Additive only; 11 new instruments |
| `config/settings.py` | 105 direct | MEDIUM | `mcp_tool_profile` field removed |
| `mcp/tools/registry.py` | via `__init__` | MEDIUM | `register_profile_tools` removed, `register_tools` added |

## Plan Conformance

| Plan Item | Status | Evidence | Note |
|-----------|--------|----------|------|
| Phase 0: SignozHost component | covered | `infra/components/signoz.py` created | |
| Phase 0: DNS record | covered | `signoz.{zone}` A record in `dns.py` | |
| Phase 0: OTEL env vars | covered | Added in `__main__.py` (not `cloudrun.py`) | Plan specified wrong file |
| Phase 0: `just signoz-tunnel` | covered | Recipe present in justfile | |
| Phase 1: silo_id on existing metrics | covered | Signatures updated | |
| Phase 1: believe.py wiring | covered | `record_belief_confidence` called | silo_id=None gap |
| Phase 1: commit.py wiring | covered | `record_belief_confidence` called | |
| Phase 1: chain_applicability | covered | `record_chain_evidence_modified` called | silo_id not passed |
| Phase 2: cache instrumentation | covered | All 3 cache files instrumented | |
| Phase 2: recall metrics | covered | latency/depth/source tracked | |
| Phase 3: remember/learn confidence | covered | `record_node_confidence` called | |
| Phase 3: supersession metrics | partial | Wired in `identities/custodian.py` not dispatch.py | Wrong metric called |
| Done: silo_id on all tools | partial | 4 tools pass None | |
| infra/signoz/docker-compose.yml | missing | Embedded in startup script instead | Functional equivalent |

**Scope creep**: Branch carries verb-promotion work (accept/reject tools, profile removal) alongside telemetry.

---

## Findings

### Blast Radius

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| B-001 | P0 | `tests/integration/test_mcp_protocol.py:50,58` | `register_all(mcp, profile="standard")` and `profile="reasoning"` - `register_all` no longer accepts `profile` argument. Tests will fail with TypeError. | Update calls to `register_all(mcp)` | S |
| B-002 | P2 | `tests/e2e/test_mcp_tools.py` | Entire file marked `pytest.mark.skip` - removes coverage from agent-surface tools | Document skip reason; track as debt | S |

### Architecture

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| A-001 | P1 | `infra/components/signoz.py` | No firewall rule targeting `signoz` tag for port 4317. Cloud Run cannot reach OTLP collector. | Add firewall rule in `NetworkStack` for tag `signoz`, port 4317, source `10.0.2.0/24` | S |
| A-002 | P2 | `infra/components/signoz.py` | Missing health check resource (StatefulHost exports `health_check_id`) | Add TCP health check on port 4317 or 3301 | S |
| A-003 | P2 | `telemetry/tracing.py:103` | `_create_exporter` hardcodes `insecure=True`; `setup_metrics` reads `OTEL_EXPORTER_OTLP_INSECURE` env var | Make trace exporter read same env var | S |
| A-004 | P2 | `infra/components/signoz.py:190` | SA scope uses full URL form; StatefulHost uses short `"cloud-platform"` | Align to short form | S |
| A-005 | P2 | `telemetry/metrics.py` | Mixed metric naming: `circuit_breaker_state` vs `recall.latency` (underscore vs dot) | Rename to dot-namespace: `store.circuit_breaker.state` | S |
| A-006 | P3 | `telemetry/metrics.py` | `_total` suffix on some counters only (`circuit_breaker_trips_total`) | Remove suffix or apply uniformly | S |
| A-007 | P3 | `cache/embedding_cache.py:42` | `record_embedding_cache_miss` never called on miss path | Add miss counter in `if data is None` branch | S |

### Error Handling

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| E-001 | P1 | `mcp/middleware.py:65` | `record_tool_error` unguarded in except block. If OTel raises, it hijacks the original exception. | Wrap in `try: ... except Exception: pass` | S |
| E-002 | P1 | `mcp/tools/recall.py:75-80` | `record_recall_latency/depth/result_count` unguarded. OTel error would mask successful recall. | Wrap all three in single try/except | S |
| E-003 | P2 | `cache/node_cache.py:123` | `record_cache_miss` in `batch_get` loop outside contextlib.suppress. OTel error discards partial results. | Guard with try/except or move inside suppress | S |
| E-004 | P2 | `mcp/tools/context_get.py:83,88,181` | Multiple inline `record_mcp_tool` calls with no error path tracking | Refactor to single try/except/finally | M |

### Logic & Spec

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| L-001 | P1 | `custodian/identities/custodian.py:178` | `record_supersession_skipped()` called on success path (when supersession IS written). Metric semantics inverted. | Call `record_supersession_used("custodian")` instead | S |
| L-002 | P2 | `mcp/tools/believe.py:47-48` | `silo_id=None` passed to metrics. `remember.py` derives correctly. | Derive `silo_id = str(derive_silo_id(auth.org_id))` | S |
| L-003 | P2 | `mcp/tools/learn.py:71,73` | Same `silo_id=None` gap | Same fix | S |
| L-004 | P2 | `mcp/middleware.py:65` | `record_tool_error` has no `silo_id` (not available in middleware context) | Accept as limitation; document | S |
| L-005 | P3 | `mcp/tools/commit.py` | Missing `record_node_confidence(layer="wisdom")` call per plan | Add call after successful commit | S |
| L-006 | P3 | `mcp/tools/remember.py:44` | Hardcodes `confidence=1.0` (plan says `result.confidence`) | Document as intentional (memory has no confidence) | S |
| L-007 | P3 | `telemetry/metrics.py:475-479` | `record_chain_evidence_modified()` has no silo_id parameter | Add optional silo_id param | S |
| L-008 | P3 | `telemetry/metrics.py` | `record_cache_eviction` defined but never called | Remove dead code or wire eviction path | S |

### Performance

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| P-001 | P1 | `mcp/tools/recall.py:83-86,116-150` | `_track_node_access` synchronous on hot path. 10 results = 10 sequential graph writes = 50-200ms. Defeats <20ms cached target. | Fire-and-forget via `asyncio.create_task()` | S |
| P-002 | P2 | `mcp/tools/recall.py:53,189` | Double timing: inner `_recall_impl` timer + outer `recall` wrapper timer. `mcp.tool.duration` includes `_track_node_access`, making it unreliable. | Use single timer; clarify what each measures | S |
| P-003 | P3 | `mcp/tools/recall.py:75-76` | `record_recall_depth` redundant with `depth` attribute on `record_recall_latency` | Merge or document distinct purpose | S |
| P-004 | P3 | `cache/result_cache.py:114-137` | `_build_key` does SHA-256 + json.dumps on every get. ~5-15us overhead. | Use tuple key for in-memory cache; hash only for Redis | M |

### AI/LLM

| ID | Priority | Location | Issue | Recommendation | Effort |
|----|----------|----------|-------|----------------|--------|
| AI-001 | P1 | `custodian/agents.py:184` | `tool_calls_limit=30` removed from `deep_pass_limits()`. `request_limit=20` is sole guard but doesn't cap tool calls within a turn. | Reinstate or document why removed | S |
| AI-002 | P2 | `custodian/agents.py:160-166,185-191` | `tool_calls_limit=0` removed from `plan_limits` and `stitch_limits`. No enforcement that these phases are tool-free. | Reinstate as defensive assertion | S |
| AI-003 | P3 | `custodian/identities/custodian.py:144` | LLM-generated `reasoning` string written to DB with no length bound | Add `max_length=500` on Pydantic field | S |

### Pre-existing (not addressed on this branch)

| ID | Priority | Location | Issue | Status |
|----|----------|----------|-------|--------|
| S-003 | P0 | `api/auth_dep.py:26-35` | Dev auth bypass in production if `AUTH_ENABLED` not set | UNRESOLVED |
| AI-P1 | P1 | `custodian/identities/*.py` | Prompt injection - DB content unsanitized in LLM prompts | UNRESOLVED |
| AI-P2 | P1 | `custodian/identities/*.py` | Missing `UsageLimits` on identity agent LLM calls | UNRESOLVED |

---

## Recommended Fix Order

1. **B-001** (P0) - Fix test signature immediately to unblock CI
2. **A-001** (P1) - Add firewall rule so telemetry actually flows
3. **E-001, E-002** (P1) - Guard telemetry in error/recall paths
4. **L-001** (P1) - Fix inverted supersession metric
5. **P-001** (P1) - Fire-and-forget `_track_node_access`
6. **L-002, L-003** (P2) - Propagate silo_id in believe/learn

Total effort: ~3-4 hours for P0+P1 fixes.
