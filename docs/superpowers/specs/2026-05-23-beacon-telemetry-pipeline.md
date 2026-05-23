# Beacon Telemetry Pipeline

Unified telemetry pipeline for Engrammic hosted service observability using beacon heartbeats and Metabase dashboards.

## Problem

Cloud Trace is hard to use, traces are inconsistent, and there's no good visibility into latency breakdown or usage patterns. We need a simpler approach that answers: what's slow, what's broken, and what are people using.

## Solution

Replace Cloud Trace with a self-hosted pipeline:
1. context-service sends heartbeats to beacon-service
2. beacon-service stores events in Postgres
3. Metabase queries Postgres for dashboards

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Cloud Run                               │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │  context-service │───▶│  beacon-service  │                   │
│  │  (MCP + API)     │    │  (telemetry rx)  │                   │
│  └──────────────────┘    └────────┬─────────┘                   │
│                                   │                              │
│  ┌──────────────────┐             │                              │
│  │    metabase      │◀────────────┼──────────────────────────┐  │
│  │  (dashboards)    │             │                          │  │
│  └────────┬─────────┘             │                          │  │
└───────────┼───────────────────────┼──────────────────────────┼──┘
            │                       │                          │
            ▼                       ▼                          │
┌───────────────────────────────────────────────────────────────┐
│                      Cloud SQL (Postgres)                      │
│  ┌────────────────┐  ┌────────────────┐  ┌─────────────────┐  │
│  │ beacon_events  │  │ beacon_secrets │  │ metabase_app_db │  │
│  └────────────────┘  └────────────────┘  └─────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

## Data Model

### TelemetryPayload (existing + additions)

| Field | Type | Description |
|-------|------|-------------|
| `install_id` | str | Instance identifier |
| `version` | str | Service version |
| `uptime_seconds` | float | Time since start |
| `total_store_ops` | int | Cumulative store calls |
| `total_recall_ops` | int | Cumulative recall calls |
| `error_rate` | float | Recent error percentage |
| `latency_mean_ms` | float | Average latency |
| `latency_p50_ms` | float | **New:** 50th percentile latency |
| `latency_p95_ms` | float | **New:** 95th percentile latency |
| `tool_counts` | dict[str, int] | **New:** MCP tool call counts |
| `silo_metrics` | dict[str, SiloMetrics] | Per-silo breakdown |

### Heartbeat interval

Reduce default from 24 hours to 1 hour for better granularity. Configurable via `TELEMETRY__BEACON_INTERVAL_HOURS`.

### Implementation notes

Changes needed to `src/context_service/telemetry/collector.py`:
1. Add `latency_p50_ms`, `latency_p95_ms`, `tool_counts` fields to `TelemetryPayload` dataclass
2. Update `_collect_aggregates()` to extract percentiles from histogram buckets
3. Add MCP tool call counting via existing `_mcp_tool_counter` metric

The `beacon_events` table stores payloads as JSONB, so no schema change needed for new fields.

## Authentication

The hosted context-service authenticates to beacon-service via `X-Beacon-Secret` header, same as future self-hosted instances.

**Setup:**
1. Pulumi generates a random secret for the hosted deployment
2. Migration inserts the secret into `beacon_secrets` with silo_id `engrammic-hosted`
3. Secret passed to context-service as `TELEMETRY__BEACON_SECRET` env var

This keeps one auth model for all beacon clients.

## Deployment

### Beacon service

- **Image:** `Dockerfile.beacon` (new)
- **Pulumi:** existing `infra/components/beacon.py`
- **Cloud Run:** scales to zero, VPC connector to Cloud SQL
- **IAM:** VPC-only invoker (no public access for now, only hosted service sends)
- **DNS:** `tel.engrammic.ai` CNAME to Cloud Run URL

### Metabase

- **Image:** official `metabase/metabase`
- **Pulumi:** new `infra/components/metabase.py`
- **Cloud Run:** stateless, app state in Cloud SQL
- **Database:** separate `metabase` database in Cloud SQL
- **DNS:** `metrics.engrammic.ai`
- **Auth:** Metabase built-in, manual first-run setup (admin email/password set on first boot)
- **IAM:** VPC-only invoker (internal dashboard)

### CI/CD

Add to GitHub Actions workflow:
- `beacon`: build and push `Dockerfile.beacon` on merge to main
- `metabase`: deploy official image (no custom build)

### Migration

- `0007_create_metabase_database.sql`: create Metabase app database
- `0008_seed_hosted_beacon_secret.sql`: insert hosted service beacon secret

## Dashboards

Initial Metabase dashboards:

1. **Health Overview** - uptime, error rate, active silos (last 24h)
2. **Latency** - p50/p95 over time, breakdown by operation type
3. **Tool Usage** - MCP tool call distribution, trends over time
4. **Per-Silo Activity** - tenant activity, store vs recall ratio

## Cleanup

Remove Cloud Trace:
- Delete `opentelemetry-exporter-gcp-trace` from dependencies
- Remove Cloud Trace exporter from `src/context_service/telemetry/tracing.py`
- Keep `@traced` decorator as no-op when disabled
- Remove `OTEL_ENABLED` from Cloud Run env config

## Out of Scope

- Self-hosted customer telemetry (beacon receiver exists, but customers sending data is future work)
- Alerting (can add via Metabase alerts later)
- Log aggregation (structlog to stdout is sufficient for now)
