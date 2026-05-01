# Devlog: Meta-Memory + Claim→Fact Wiring

**Date:** 2026-05-01
**Author:** Claude + NovusEdge

## Summary

Wired three deferred features from the EAG integration audit and meta-memory roadmap:

1. **Provenance queries (Meta-Memory Phase 1)** - now traverse REFERENCES edges
2. **Reflection retrieval** - new `context_get_reflections` MCP tool
3. **Claim→Fact promotion** - refactored from multi-labeling to separate :Fact nodes

## Changes

### Provenance Fix

Added `|REFERENCES` to `PROVENANCE_CHAIN` and `PROVENANCE_ROOT_SOURCES` queries in `db/queries.py`. The `context_provenance` tool now traces citation chains all the way to source Documents, not just to Claims.

### Reflection Retrieval

New MCP tool `context_get_reflections(silo_id, node_id)` retrieves MetaObservations linked via ABOUT edges to a target node.

Files:
- `src/context_service/db/queries.py` - added `GET_REFLECTIONS_FOR_NODE` query
- `src/context_service/services/context.py` - added `get_reflections()` method
- `src/context_service/mcp/tools/context_get_reflections.py` - new tool
- `src/context_service/mcp/tools/__init__.py` - registered tool

### Claim→Fact Topology Change

**Before:** `PROMOTE_CLAIM_TO_FACT` added a `:Fact` label to the existing `:Claim` node (multi-labeling).

**After:** Creates a new `:Fact` node with copied properties and a `(:Fact)-[:PROMOTED_FROM]->(:Claim)` edge. This is consistent with the Finding promotion pattern and enables edge-based provenance traversal.

Files:
- `src/context_service/db/queries.py` - rewrote `PROMOTE_CLAIM_TO_FACT`
- `src/context_service/services/context.py` - updated `promote_claim_to_fact()` to generate fact_id
- `src/context_service/pipelines/assets/fact_promotion.py` - updated batch promotion

## Audit Updates

- `eag-integration-audit.md` - marked #6 (primitives.eag.epistemology integration) as resolved
- `meta-memory-roadmap.md` - marked Phase 1 complete, Phase 4 partially complete

## Testing

- `just test` passes
- `just check` passes (after fixing pre-existing SIM105 lint issues in `test_hybrid_retrieval.py`)
- Manual MCP testing pending (needs docker stack)

## Deferred

- MetaObservation not yet in `primitives.schema.labels`
- ABOUT edge not yet in `CITEEdgeType`
- No indexes on `:MetaObservation` (uses existing node indexes)
