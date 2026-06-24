# Self-Hosted Quickstart

Get Engrammic running on your own infrastructure in under 10 minutes.

## Prerequisites

- Docker 20.10+ with Compose v2
- 4GB RAM minimum (8GB recommended for production)
- License key from [engrammic.ai/self-hosted](https://engrammic.ai/self-hosted)

## Install

Download and run the installer:

```bash
curl -fsSL https://get.engrammic.ai | sh
```

Then run the Docker setup:

```bash
engrammic docker
```

The installer will:
1. Validate your license key
2. Create an `engrammic/` directory with `docker-compose.yml` and `.env`

## Configure

Edit `engrammic/.env`:

```bash
# Required: set a strong password
POSTGRES_PASSWORD=your-secure-password-here

# Optional: enable full SAGE features (synthesis, deduplication)
# LLM_PROVIDER=openai
# LLM_API_KEY=sk-...
```

Without LLM keys, Engrammic runs in passive mode: memory storage and recall work, but automatic synthesis is disabled.

## Start

```bash
cd engrammic
docker compose up -d
```

Wait for all services to become healthy (about 30 seconds):

```bash
docker compose ps
```

All services should show `healthy` status.

## Verify

Check the health endpoint:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "0.1.0",
  "services": {
    "memgraph": "connected",
    "redis": "connected",
    "qdrant": "connected",
    "postgres": "connected"
  },
  "sage_mode": "passive",
  "license": {
    "valid": true,
    "customer": "your-org",
    "days_remaining": 87
  }
}
```

## Configure Your Editor

### Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "engrammic": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "engrammic": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## Diagnostics

If something goes wrong:

```bash
# Check container health and resource usage
engrammic doctor

# Monitor memory usage
engrammic scale
```

## Upgrading

Pull the latest images and restart:

```bash
cd engrammic
docker compose pull
docker compose up -d
```

Deprecation warnings appear in logs when running old versions.

## Telemetry

By default, anonymous usage metrics are sent to help improve Engrammic. No content or user data is collected.

To disable:

```bash
# In engrammic/.env
TELEMETRY_ENABLED=false
```

See [telemetry.md](telemetry.md) for details on what's collected.

## Next Steps

- [Telemetry configuration](telemetry.md)
- [MCP tools reference](https://docs.engrammic.ai/mcp-tools)
