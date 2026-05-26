# Telemetry

Engrammic collects anonymous usage metrics to improve the product.

## What's Collected

- Startup events (version, configuration flags)
- Aggregate operation counts (recalls, stores)
- Error rates and types

## What's NOT Collected

- Memory content or user data
- Queries or search terms
- Personal information

## Configuration

Telemetry is enabled by default. To disable:

```bash
# In engrammic/.env
TELEMETRY_ENABLED=false
```

## Data Destination

Metrics are sent to `tel.engrammic.ai`. No data is shared with third parties.
