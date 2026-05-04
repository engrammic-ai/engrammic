# Delta Prime

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
uv sync --all-extras

# Run
just dev

# Test
just test
```

## Port status

Port from prototype completed 2026-04-26. The checklist below is retained for reference; all items are done.

1. config/ - settings, logging — done
2. stores/ - Memgraph, Qdrant, Redis clients — done
3. embeddings/ - Jina, Vertex — done
4. signals/ - heat, freshness, priority — done
5. mcp/ - server + tools — done
6. pipelines/ - Dagster — done
7. api/ - admin routes — done

