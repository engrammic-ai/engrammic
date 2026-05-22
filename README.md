# Engrammic Context Service

Production backend for Engrammic. Exposes MCP server (agent surface) and FastAPI (admin).

## Quick Start

```bash
uv sync --all-extras    # Install deps
just up                 # Start local stack (Memgraph, Qdrant, Redis)
just dev                # Run FastAPI with reload
```

## Commands

| Command | What it does |
|---------|--------------|
| `just check` | Lint + typecheck (must pass before merge) |
| `just test` | Run pytest (takes args: `just test -k name`) |
| `just ci` | check + test (pre-push) |
| `just db-migrate` | Run migrations |
| `just dagster-web` | Dagster UI for Custodian jobs |

## Structure

```
src/context_service/
├── mcp/           # MCP server + tools (primary agent surface)
├── api/           # FastAPI admin routes
├── auth/          # WorkOS + OAuth
├── config/        # Settings, logging
├── signals/       # Heat, freshness, priority
├── embeddings/    # Jina, Vertex, SPLADE clients
├── stores/        # Memgraph, Qdrant, Redis
├── engine/        # Storage protocols (depend on this, not stores)
└── pipelines/     # Dagster assets, sensors, jobs
```

## Key Paths

- `config/mcp_tools.yaml` - MCP tool surface (source of truth for names/descriptions)
- `engine/protocols.py` - storage interfaces (depend on this, not concrete stores)
- `context/plans/` - active implementation plans
- `context/architecture.md` - full architecture doc

## Dependencies

| Service | Purpose |
|---------|---------|
| Memgraph | Graph store |
| Qdrant | Vector store |
| Redis | Cache, queues, heat scores, rate limits |
| Dagster | Pipeline orchestration |
| primitives | Schema library (editable from `../primitives`) |

## Rate Limits

| Tier | Write RPM | Read RPM |
|------|-----------|----------|
| Free | 20 | 60 |
| Starter | 60 | 200 |
| Pro | 200 | 600 |
| Enterprise | 1000 | 3000 |

Enable: `SECURITY__RATE_LIMIT__ENABLED=true`
