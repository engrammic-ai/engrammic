# context-service

Delta Prime production backend. Private repo.

## Structure

```
src/context_service/
├── config/        # Settings, logging (ported from contextr)
├── signals/       # Heat, freshness, priority (proprietary)
├── embeddings/    # Jina, Vertex, SPLADE clients
├── stores/        # Memgraph, Qdrant, Redis clients
├── mcp/           # MCP server + tools
├── api/           # FastAPI admin routes
├── auth/          # WorkOS (deferred)
└── pipelines/     # Dagster assets, sensors, jobs
```

## Dependencies

- **primitives**: Open-source lib (submodule during dev, PyPI once stable)
- **Memgraph**: Graph store
- **Qdrant**: Vector store
- **Redis**: Cache, queues, heat scores
- **Dagster**: Pipeline orchestration

## Development

```bash
# Install
uv pip install -e ".[dev]"

# Run
just dev

# Test
just test
```

## Porting from contextr

Modules to port (in order):
1. config/ - settings, logging
2. stores/ - Memgraph, Qdrant, Redis clients
3. embeddings/ - Jina, Vertex
4. signals/ - heat, freshness, priority
5. mcp/ - server + tools
6. pipelines/ - Dagster (discuss DAG first)
7. api/ - admin routes
