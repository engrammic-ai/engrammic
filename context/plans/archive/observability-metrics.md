# Plan: Observability and Metrics

**Status:** COMPLETE 2026-05-02
**Branch:** `phase-observability`
**Workstream:** v1.0 pre-requisite

## Goal

Production-grade observability: structured metrics, alerting hooks, and dashboards. Partners need visibility into what the system is doing; ops needs to know when things break.

## Why

Current state:
- Structlog for logs (good)
- Health checks on stores (good)
- No metrics export
- No latency histograms
- No alert hooks
- No usage metering per silo

Before partner onboarding, we need to answer:
- "How many queries is silo X running?"
- "What's p95 latency for context_query?"
- "Did extraction fail rate spike?"

## Scope

### Must have (v1.0)

1. **Prometheus metrics endpoint** (`/metrics`)
   - Request latency histograms (by tool/endpoint)
   - Request counts (by tool, status, silo_id)
   - Active connections (Memgraph, Qdrant, Redis)
   - Error rates by category

2. **Key business metrics**
   - `context_query_latency_seconds` (histogram)
   - `context_store_latency_seconds` (histogram)
   - `extraction_claims_total` (counter, by silo)
   - `custodian_promotions_total` (counter)
   - `custodian_rejections_total` (counter, by reason)

3. **Infrastructure metrics**
   - Pool utilization (Memgraph, Redis)
   - Queue depths (if applicable)
   - Cache hit rates (embedding, node)

4. **Alerting hooks**
   - Expose metrics in Prometheus format
   - Document recommended alert rules
   - Integration guide for Grafana/Datadog/etc.

### Nice to have (v1.1)

- Per-silo usage dashboards
- Billing-ready metering (request counts, storage)
- Trace correlation (OpenTelemetry spans)
- SLO tracking (latency budgets)

## Implementation

### Dependencies
- `prometheus-client` or `starlette-prometheus`
- No new infra (metrics scraped by partner's Prometheus)

### Files to create/modify
- `src/context_service/api/metrics.py` - metrics registry + `/metrics` endpoint
- `src/context_service/api/middleware.py` - request timing middleware
- `src/context_service/mcp/metrics.py` - MCP tool metrics
- `docs/operations/metrics.md` - metric catalog + alert recommendations

### Tasks

1. **Add prometheus-client dependency**
2. **Create metrics registry** with core counters/histograms
3. **Add timing middleware** for FastAPI routes
4. **Instrument MCP tools** (decorator or manual timing)
5. **Instrument store operations** (Memgraph, Qdrant, Redis)
6. **Expose /metrics endpoint**
7. **Document metrics catalog**
8. **Add recommended Grafana dashboard JSON** (optional)

## Out of scope

- Hosted metrics/monitoring (partners bring their own)
- Log aggregation (structlog already outputs JSON)
- APM/tracing (defer to v1.1 with OpenTelemetry)
- Billing integration

## Done criteria

- `/metrics` returns Prometheus-format metrics
- p50/p95/p99 latency visible for core operations
- Error rates trackable by category
- Docs explain what each metric means and suggested alerts
- `just check` green
