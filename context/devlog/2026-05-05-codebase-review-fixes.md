# Codebase Review Fixes

**Date:** 2026-05-05  
**Review:** `context/review/codebase-review-2026-05-05.md`  
**Commits:** `57f2dbd`, `dedc51d`

## Summary

Addressed 48 findings from full codebase review. Parallel subagent execution (4 Sonnet agents) completed fixes in ~15 minutes.

## P0/P1 Fixes

### Performance: N+1 Query Batching

- **context.py**: `assert_claim`, `commit_belief`, `reflect` now batch edge creation with UNWIND queries instead of per-item loops
- **write_path.py**: CITES and PROPOSED_EDGE batched via `CITES_EDGE_CREATE_NODE_BATCH` and `PROPOSED_EDGE_MERGE_BATCH`
- **context.py**: `provenance` and `history` use `asyncio.gather` for parallel queries
- **redis.py**: Added `mset` method for batch cache writes

### Error Handling

- **memgraph.py**: Raise `MemgraphOperationError` on retry exhaustion instead of silent `return []`
- **evidence.py**: Added exponential backoff (3 retries: 0.5s, 1s, 2s) to `_validate_uri`
- **auto_reflection.py**: Returns `tuple[str | None, Exception | None]` for error visibility

### AI/LLM Validation

- **extraction/service.py**: Added `MAX_CONTENT_SIZE = 100_000` and `MAX_RELATIONSHIPS = 500` limits

### Config

- **settings.py**: Default host changed to `127.0.0.1`

## Dead Code Removal

### Queries Removed (12)
- `CREATE_CAUSES_EDGE`, `CREATE_CONCLUDES_EDGE`, `CREATE_CONTRADICTS_EDGE`, `CREATE_CORROBORATES_EDGE`
- `CREATE_ENTITY`, `ENTITY_NEIGHBORHOOD_NODES`
- `FIND_ENTITY_BY_NAME`, `FIND_ENTITY_BY_ALIAS`, `FIND_ENTITIES_BY_NAME_TOKENS`
- `ATTACH_CLAIM_TO_DOCUMENT`, `ATTACH_CLAIM_REFERENCES_DOC`
- `FIND_ORPHANED_ACTIVE_CONCLUSIONS`

### Classes/Functions Removed
- `ClusterMembership` (clustering/models.py)
- `GraphNode`, `GraphEdge` (services/models.py)
- `filter_cyclic_pairs` (custodian/supersession.py)

### LLM Shims Removed
- `llm_api_key`, `llm_model`, `llm_api_url` (per-provider keys used instead)

## Config Cleanup

- Cache classes now use `settings.node_cache_ttl` / `settings.embedding_cache_ttl` instead of hardcoded values

## TODO: Future Work

### BEAR Compression Subsystem
Settings exist but subsystem not implemented:
- `bear_api_key`, `bear_api_url`, `bear_timeout_ms`, `bear_enabled`
- Purpose: External compression service for large content

### Unused Config Settings (Low Priority)
Some settings identified as potentially unused:
- **Dead feature gates**: `entity_retrieval_enabled`, `cluster_retrieval_enabled`, `commitment_retrieval_enabled`, `walker_entity_graph_mode`
- Nested sub-configs were falsely flagged - they ARE used (see above)

### Config Architecture (Resolved)
Initial audit claimed nested configs were unused. On verification, they ARE used:
- Re-exported from `core/__init__.py` for external access
- Used in type signatures (e.g., `CustodianSettings` in visit.py)
- Flat properties read from nested objects internally

Architecture is correct: nested for organization, flat properties for convenience. Added `frozen=True` for immutability.

## Files Changed

### Source (22 files)
- `config/settings.py` - host default, removed LLM shims, BEAR TODO
- `cache/node_cache.py`, `cache/embedding_cache.py` - TTL from settings
- `db/queries.py` - removed 12 queries, added batch queries
- `db/custodian_queries.py` - added batch edge queries
- `services/context.py` - batched edges, asyncio.gather
- `custodian/write_path.py` - batched CITES/PROPOSED_EDGE
- `stores/memgraph.py` - error on retry exhaustion
- `stores/redis.py` - mset method
- `extraction/service.py` - content/relationship limits
- `engine/auto_reflection.py` - tuple return type
- `services/evidence.py` - backoff retry
- Plus: removed dead code from models, cleaned imports

### Tests (7 files)
- Removed tests for deleted code
- Updated `test_auto_reflection.py` for tuple return
