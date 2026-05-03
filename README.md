# context-service

Delta Prime production backend. Private repo.

## Provenance

Ported from [NovusEdge/CTXR](https://github.com/NovusEdge/CTXR) (the `prototype` research prototype) on 2026-04-26 in a single session (~150 files, 0 lint/type errors on completion). The port moved architecture docs, EAG specs, RAG-era specs, and all service source into the `delta-prime` monorepo structure. `primitives` was separated into its own package during this session.

Original prototype repo retains the full RAG-era development history (phases 1–8, brainstorms, benchmarks). This repo is the forward-moving production codebase.

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

For deferred EAG integration items see `context/plans/eag-integration-audit.md`.
