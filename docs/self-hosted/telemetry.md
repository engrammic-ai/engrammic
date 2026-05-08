# Telemetry

Engrammic collects anonymous telemetry to improve the product and enable support.

## Tiers

**Tier 1 (default):** Anonymous aggregate metrics
- Install ID (random UUID, regenerates if deleted)
- Version and uptime
- Total operation counts (no per-tenant breakdown)
- Global latency percentiles and error rates

**Tier 2 (opt-in):** Per-tenant metrics
- Everything in Tier 1
- Per-silo operation counts and latencies
- Enables Engrammic support to help debug tenant-specific issues

## Configuration

```bash
# Tier 1: anonymous aggregate (default)
ENGRAMMIC_TELEMETRY__ENABLED=true

# Disable all telemetry
ENGRAMMIC_TELEMETRY__ENABLED=false

# Tier 2: specific tenants
ENGRAMMIC_TELEMETRY__SILOS=tenant-a,tenant-b

# Tier 2: all tenants
ENGRAMMIC_TELEMETRY__SILOS=*
```

## Local Metrics

Regardless of beacon settings, all metrics are available at `/metrics` in Prometheus format with `silo_id` labels for your own monitoring.
