# Telemetry and Observability Design

**Date:** 2026-05-25
**Status:** Draft
**Linear:** ENG-32

## Summary

Add full observability stack for closed beta: self-hosted SigNoz on dedicated VM, instrumentation for performance visibility and epistemic health monitoring.

## Goals

1. Answer "why is recall slow?" with cache hit rates and latency breakdown
2. Understand agent behavior: supersession usage, confidence calibration, hypothesis lifecycle
3. Meet performance SLOs in CLAUDE.md (recall cached < 20ms, search < 250ms, etc.)
4. Operate confidently with early beta users

## Non-Goals

- Alerting (defer until post-beta)
- Dagster asset instrumentation (defer — Dagster has its own UI)
- Full distributed tracing across all services (start with metrics, add traces as needed)

---

## Phase 0: SigNoz Infrastructure (~1 day)

### New Pulumi Component: `SignozHost`

Dedicated GCE VM for observability stack, isolated from core data stores.

| Spec | Value |
|------|-------|
| Instance | `e2-standard-4` (4 vCPU, 16GB RAM) |
| Disk | 100GB SSD (ClickHouse storage) |
| Region | Same as StatefulHost (europe-north1) |

### Docker Compose Stack

```yaml
services:
  clickhouse:
    image: clickhouse/clickhouse-server:23.8-alpine
    mem_limit: 8g
    volumes:
      - clickhouse-data:/var/lib/clickhouse

  signoz-otel-collector:
    image: signoz/signoz-otel-collector:0.88.x  # pin version
    mem_limit: 1g
    ports:
      - "4317:4317"  # OTLP gRPC
      - "4318:4318"  # OTLP HTTP

  signoz-query-service:
    image: signoz/query-service:0.45.x  # pin version
    mem_limit: 2g

  signoz-frontend:
    image: signoz/frontend:0.45.x  # pin version
    mem_limit: 512m
    ports:
      - "3301:3301"
```

### Networking and Security

- **Internal DNS:** `signoz.engrammic.internal` via existing InternalDNS component
- **OTEL endpoint:** VPC-internal only, no public exposure
- **UI access:** IAP tunnel (no public exposure)
- **Firewall:** Allow 4317/4318 from context-service only, 3301 via IAP

### Context Service Changes

```python
# Add to env vars in Pulumi ContextServiceRun
"OTEL_ENABLED": "true",
"OTEL_EXPORTER_OTLP_ENDPOINT": "http://signoz.engrammic.internal:4317",
"OTEL_SERVICE_NAME": "engrammic",
```

### Retention Policy

- Traces: 7 days
- Metrics: 30 days
- Configure in SigNoz settings post-deploy

### Gotchas

- ClickHouse compaction spikes CPU/disk — runs off-peak by default
- Pin SigNoz versions — upgrades require manual migration
- Set memory limits in compose to prevent OOM on complex queries

---

## Phase 1: Wire Existing Metrics (~0.5 day)

Metrics already defined in `telemetry/metrics.py` but never called.

| Metric | Where to Wire | Tags |
|--------|---------------|------|
| `record_edge_confidence` | `_context_store.py` when creating evidence edges | `silo_id`, `layer` |
| `record_belief_confidence` | `believe.py`, `commit.py` | `silo_id` |
| `record_chain_evidence_modified` | `chain_applicability.py:408` (complete stub) | `silo_id` |

### Tag Consistency Audit

Add `silo_id` to all existing `record_*` calls that are missing it:
- `record_mcp_tool` — add `silo_id`
- `record_embedding` — add `silo_id`
- `record_llm_call` — add `silo_id`

---

## Phase 2: Recall and Cache Visibility (~2 days)

### 2a: Recall Latency (Priority)

Directly tied to performance targets in CLAUDE.md.

| Metric | Location | Tags | Notes |
|--------|----------|------|-------|
| `recall.latency_ms` | `recall.py` | `silo_id`, `depth`, `source` | Histogram with p50/p95/p99 |
| `recall.depth` | `recall.py` | `depth` (0-3), `silo_id` | Counter |
| `recall.result_count` | `_context_recall` | `layer`, `silo_id` | Histogram |
| `recall.source` | `recall.py` | `source` (cache/search/graph) | Counter |

### 2b: Cache Hit Rates

| Metric | Location | Tags |
|--------|----------|------|
| `cache.result.hit` / `cache.result.miss` | `result_cache.py` | `silo_id` |
| `cache.node.hit` / `cache.node.miss` | `node_cache.py` | `silo_id` |
| `cache.alias.hit` / `cache.alias.miss` | `alias_cache.py` | `silo_id` |
| `cache.eviction` | All cache modules | `cache_type`, `silo_id` |

---

## Phase 3: Epistemic Health and Errors (~1.5 days)

### Error Tracking

| Metric | Location | Tags |
|--------|----------|------|
| `tool.error` | MCP tool wrappers | `tool_name`, `error_type`, `silo_id` |

### Supersession Tracking

| Metric | Location | What it Shows |
|--------|----------|---------------|
| `store.supersession_used` | `_context_store.py` | Agent passed `supersedes` arg |
| `store.supersession_skipped` | Custodian duplicate detection | Custodian caught what should have been supersession |

### Confidence Calibration

| Metric | Location | Tags |
|--------|----------|------|
| `node.confidence` | Write paths (remember, learn, believe, commit) | `layer`, `silo_id` |

### Capacity Planning (Periodic Gauge)

| Metric | Source | Tags |
|--------|--------|------|
| `graph.node_count` | Dagster job or periodic task | `silo_id`, `layer` |
| `graph.edge_count` | Dagster job or periodic task | `silo_id` |

---

## Deferred (Post-Beta)

- `belief.synthesis_proposed/accepted/rejected` — SAGE synthesizer effectiveness
- `knowledge.evidence_count` histogram — evidence richness
- `hypothesis.time_to_commit` histogram — hypothesis lifecycle
- `link.relationship_type` counter — relationship type distribution
- Alerting via AlertManager
- Dagster asset instrumentation

---

## Success Criteria

1. SigNoz UI accessible via IAP tunnel
2. MCP tool latency visible in dashboards
3. Cache hit rates measurable per silo
4. Can answer "why was this recall slow?" with trace/metrics

---

## Estimated Effort

| Phase | Effort | Dependencies |
|-------|--------|--------------|
| Phase 0 | 1 day | None |
| Phase 1 | 0.5 day | Phase 0 |
| Phase 2a | 1 day | Phase 0 |
| Phase 2b | 1 day | Phase 0 |
| Phase 3 | 1.5 days | Phase 0 |

**Total:** ~5 days (1 week with buffer)

---

## Open Questions

None — IAP tunnel access will be via justfile command (e.g., `just signoz-tunnel`).
