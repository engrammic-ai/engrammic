# Engrammic

Cognitive substrate for AI agents. Context infrastructure that understands, not just stores.

Private repo.

## Structure

```
src/context_service/
├── config/        # Settings, logging (ported from prototype)
├── signals/       # Heat, freshness, priority (proprietary)
├── embeddings/    # Jina, Vertex, SPLADE clients
├── stores/        # Memgraph, Qdrant, Redis clients
├── mcp/           # MCP server + tools
├── api/           # FastAPI admin routes
├── auth/          # WorkOS + OAuth tokens
└── pipelines/     # Dagster assets, sensors, jobs
```

## Features

- **MCP Server**: Intent-based tools (remember, learn, believe, recall, etc.)
- **Tiered Rate Limiting**: Per-org RPM limits by pricing tier (free/starter/pro/enterprise)
- **Custodian Pipeline**: Background synthesis, fact promotion, belief merging
- **Heat Diffusion**: Relevance signals via graph-based heat propagation
- **Multi-tenancy**: Silo isolation per org

## Rate Limiting

Tiered rate limiting protects against abuse and enforces pricing tiers.

| Tier | MCP Write RPM | MCP Read RPM |
|------|---------------|--------------|
| Free | 20 | 60 |
| Starter | 60 | 200 |
| Pro | 200 | 600 |
| Enterprise | 1000 | 3000 |

Enable: `SECURITY__RATE_LIMIT__ENABLED=true`

Set tier: `PATCH /admin/silos/{silo_id}/tier` with `{"tier": "pro"}`

## Dependencies

- **primitives**: Open-source lib (submodule during dev, PyPI once stable)
- **Memgraph**: Graph store
- **Qdrant**: Vector store
- **Redis**: Cache, queues, heat scores, rate limit counters
- **Dagster**: Pipeline orchestration

## Development

```bash
# Install
uv sync --all-extras

# Run
just dev

# Test
just test
```


