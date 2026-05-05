# Devlog: Auto-Tagging System

**Date:** 2026-05-05  
**Scope:** Hybrid sync/async auto-tagging with per-silo vocabulary in Postgres

---

## Summary

Implemented a complete auto-tagging system that automatically suggests and applies tags to stored content. Uses a two-phase approach: fast sync cosine matching at write time, async LLM refinement via Dagster.

## What We Built

### Infrastructure (Postgres)

- Added SQLAlchemy 2.0 + asyncpg + Alembic to the stack
- Created `SiloTagConfig` model for per-silo tag vocabulary
- Alembic migration for `silo_tag_configs` table
- Async session management with connection pooling
- Docker service + env vars (`POSTGRES_HOST`, `POSTGRES_USER`, etc.)

### Core Services

- **TagConfigService** - CRUD for per-silo tag configuration (core tags, dynamic tags, settings, constraints)
- **AutoTaggingService** - Sync cosine matching using numpy (~0.1ms), vocabulary caching with 5min TTL

### Dagster Assets

- **auto_tagging** - Every 30min: LLM-based tag refinement for nodes missing `auto_tagged_at`
- **tag_maintenance** - Daily at 03:00 UTC: prunes stale dynamic tags not used in N days

### Integration

- Wired into `ContextService.store()` - auto-tags merged with user tags on every write
- App lifecycle: `init_postgres()` / `close_postgres()` in FastAPI lifespan
- `AutoTaggingService` injected into MCP tool surface

## Architecture

```
store() call
    |
    v
[Sync: ~0.1ms] cosine match against cached vocabulary
    |
    v
Merge user_tags + auto_tags, write to Memgraph
    |
    v
[Async: every 30min] LLM refines tags for untagged nodes
    |
    v
[Async: daily] Prune unused dynamic tags
```

## Key Decisions

1. **Postgres for tag config** - Dashboard needs SQL queries; Memgraph is awkward for config CRUD
2. **Sync cosine over async LLM at write time** - Latency budget is tight; numpy is fast enough
3. **Flat env vars** - `POSTGRES_HOST` not `INFRA__POSTGRES__HOST` to match existing patterns
4. **Per-silo vocabulary** - Multi-tenant isolation maintained throughout

## Files Changed

| Path | Purpose |
|------|---------|
| `src/context_service/db/postgres.py` | Async session factory |
| `src/context_service/models/tag_config.py` | SiloTagConfig model |
| `src/context_service/services/tag_config.py` | CRUD service |
| `src/context_service/services/auto_tagging.py` | Cosine matching |
| `src/context_service/pipelines/assets/auto_tagging.py` | LLM refinement asset |
| `src/context_service/pipelines/assets/tag_maintenance.py` | Vocabulary pruning asset |
| `src/context_service/pipelines/schedules.py` | 30min + daily schedules |
| `src/context_service/config/tags.yaml` | System defaults |
| `alembic/` | Migration infrastructure |
| `docker-compose.yml` | Postgres service |

## Test Coverage

- 936 tests passing
- New tests for VocabCache, AutoTaggingService, TagConfigService, Dagster assets

## Commands

```bash
# Run migration
uv run alembic upgrade head

# Docker stack
docker compose up -d
docker compose exec app alembic upgrade head
```

## Next Steps

- Wire promotion logic (Redis candidate tracking -> dynamic_tags promotion)
- Add MCP admin endpoint for tag vocabulary management
- Consider SPLADE for hybrid sparse+dense matching
