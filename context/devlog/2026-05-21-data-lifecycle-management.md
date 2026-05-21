# Data Lifecycle Management

**Date:** 2026-05-21  
**Branch:** feat/data-lifecycle-management  
**Status:** Complete, merged to main and beta

## Summary

Implemented comprehensive data lifecycle management: agent-driven forget tool, GDPR erasure endpoint, chain pruning, and retention policy enhancements. Three-store consistency achieved via graph-as-source-of-truth pattern with query-time tombstone filtering.

## Architecture Decisions

### Graph-as-Source-of-Truth for Deletions

Rather than synchronizing deletes across Memgraph, Qdrant, and Redis simultaneously, we:

1. **Tombstone in Memgraph** (source of truth) - set `tombstoned_at` timestamp
2. **Invalidate Redis cache** (immediate consistency) - delete cache key on tombstone
3. **Filter at query time** - `WHERE tombstoned_at IS NULL` in Cypher
4. **Hard delete later** - retention GC removes tombstoned nodes and their Qdrant vectors

This avoids split-brain scenarios where Memgraph succeeds but Qdrant fails (which happened when Qdrant points don't exist for older nodes).

### Cancel Window Pattern

Forget operations enter a 1-hour cancel window before becoming permanent. Users can call `cancel_forget` within this window to restore the node. After the window, the retention GC asset performs hard deletion.

## Changes

### MCP Surface

- **forget tool** (`mcp/tools/forget.py`): Agent-driven deletion with optional cascade. Tombstones node, invalidates cache, optionally tombstones downstream references.

- **Cascade logic**: When `cascade=True`, finds nodes with edges pointing to the target and tombstones them recursively.

### REST API

- **GDPR erasure** (`api/routes/admin.py`): `DELETE /api/v1/admin/silo/{silo_id}/nodes/{node_id}/gdpr-erasure` - admin endpoint for compliance-driven hard deletion bypassing cancel window.

### Retention Pipeline

- **ForgetService** (`retention/forget_service.py`): Core tombstoning logic. Sets `tombstoned_at` and `forget_reason`, returns downstream reference count.

- **Chain pruning** (`pipelines/assets/chain_pruning.py`): Dagster asset that tombstones reasoning chains older than retention threshold (default 30 days for compacted chains).

- **Retention GC** (`pipelines/assets/retention_gc.py`): Hard-deletes tombstoned nodes past cancel window. Removes from Memgraph, Qdrant, and related edges.

- **SiloConfig enhancements** (`retention/silo_config.py`): Per-silo retention policies with `resolve()` method for hierarchical config (silo -> org -> global defaults).

### Query Path Updates

- **_batch_fetch_nodes** (`services/context.py`): Added `WHERE n.tombstoned_at IS NULL` filter to exclude tombstoned nodes from all recall operations.

## Bug Fixes

### Qdrant Sync 404 (Fixed in beta)

**Problem:** Forget tool failed with "No point with id X found" when calling `set_payload` on Qdrant points that don't exist (nodes created before Qdrant integration or indexing failures).

**Solution:** Removed Qdrant sync from ForgetService entirely. Graph is source of truth; tombstoned nodes are filtered at query time and eventually hard-deleted by retention GC (which handles Qdrant cleanup).

### Cache Returning Tombstoned Nodes (Fixed)

**Problem:** Tombstone filter only applied to graph query, not cached results. Nodes could still be returned from Redis cache after tombstoning.

**Solution:** Added cache invalidation in forget tool - `cache.delete(f"node:{silo_id}:{node_id}")` on successful tombstone.

## Files Changed

### Source
- `mcp/tools/forget.py` - MCP tool (new)
- `retention/forget_service.py` - tombstone service (new)
- `retention/silo_config.py` - retention policy resolution
- `api/routes/admin.py` - GDPR endpoint
- `pipelines/assets/chain_pruning.py` - chain pruning asset (new)
- `pipelines/assets/retention_gc.py` - hard deletion asset (new)
- `services/context.py` - tombstone filter in _batch_fetch_nodes
- `db/queries.py` - FORGET_NODE Cypher mutation

### Tests
- `tests/mcp/tools/test_forget.py` (new)
- `tests/retention/test_forget_service.py` (new)
- `tests/api/test_gdpr_erasure.py` (new)
- `tests/pipelines/test_chain_pruning.py` (new)

## Verification

Tested on beta (2026-05-21):
1. Created test node via `remember`
2. Forgot node via `forget` - returned `status: tombstoned`
3. Direct fetch via `recall` - returned `node_not_found`
4. Search query - tombstoned node filtered from results

Cache invalidation confirmed working immediately after tombstone.
