# Ultrareview Fixes: Belief Tools

**Date:** 2026-05-07  
**Review:** Ultrareview (cloud-based, 8 findings across 51 changed files)  
**Scope:** New belief lifecycle tools from cognitive-runtime-pivot

## Summary

Ultrareview identified 8 issues in the new belief tools shipped in the cognitive-runtime-pivot. One security regression (cross-tenant data exposure), five normal-severity bugs, and two nits. All fixed in single pass.

## Security Fix

### bug_012: Silo Ownership Validation Missing from Belief Tools

The three new MCP tools (`context_belief_state`, `context_update_belief`, `context_crystallize`) and the `belief` branch of `context_store` all skipped `validate_silo_ownership()`. Every other MCP tool calls this guard.

**Impact:** A caller authenticated as org A could pass an explicit `silo_id` for org B (computable via `derive_silo_id(orgB_org_id)`) and read/write/crystallize beliefs in the wrong tenant.

**Fix:** Added the standard pattern to all four code paths:
```python
if silo_id is not None:
    err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
    if err is not None:
        return err
```

**Files:** `context_belief_state.py`, `context_update_belief.py`, `context_crystallize.py`, `context_store.py`

## Normal Severity Fixes

### merged_bug_001: CRYSTALLIZE_TO_COMMITMENT Query Bugs

Two issues in the Cypher:
1. Row multiplication: `MATCH (wb)-[:ABOUT]->(n)` after `collect()` re-expanded rows, causing K x M SUPERSEDES edges instead of M
2. Missing `layer: "wisdom"` property, so crystallized Commitments were invisible to `context_recall(layers=["wisdom"])`

**Fix:** Added `WITH DISTINCT cm, to_supersede` before FOREACH, added `layer: "wisdom"` to CREATE.

**File:** `db/queries.py`

### bug_023: created_at Int Handling in get()

`ContextService.get()` only handled string timestamps from Memgraph, but `store()` writes with Cypher `timestamp()` which returns int microseconds. When cache was enabled, `node.created_at.isoformat()` crashed with AttributeError.

**Fix:** Added int branch mirroring `_batch_fetch_nodes`:
```python
elif isinstance(raw_created_at, int):
    created_at = datetime.fromtimestamp(raw_created_at / 1_000_000, tz=UTC)
```

**File:** `services/context.py`

### merged_bug_009: partial_confidence Double-Discount

`assert_claim` now stores discounted confidence under `claim.confidence` and raw under `raw_confidence`. But `fact_promotion.py` still read `confidence`, applying the source-tier weight twice. R1 promotion threshold (0.7) became unreachable for authoritative-tier claims.

**Fix:** Read `raw_confidence` with fallback:
```python
raw_confidence = float(claim_props.get("raw_confidence", claim_props.get("confidence", 0.0)))
```

**File:** `custodian/fact_promotion.py`

### bug_029: context_belief_state About-Filter Skips Contradictions

When `about` parameter filtered `working_beliefs`, the contradiction query still ran unscoped. Response could show `reflection_suggested=True` with contradiction pairs referencing belief_ids not in the response.

**Fix:** Post-filter contradictions to only include pairs where both belief_ids are in the filtered beliefs set.

**File:** `mcp/tools/context_belief_state.py`

### bug_006: include_steps/include_reflections Dropped with include_content=False

`_project_node_without_content` projected to exactly 5 fields, dropping freshly-attached `steps` and `reflections` keys. Wasted Postgres/Memgraph round-trips.

**Fix:** Preserve keys if present:
```python
if "steps" in node:
    projected["steps"] = node["steps"]
if "reflections" in node:
    projected["reflections"] = node["reflections"]
```

**File:** `mcp/tools/context_recall.py`

## Nits

### bug_004: Confidence Validation Missing from Belief Layer

`_context_store_belief` accepted any float for confidence, unlike `_context_assert` which validates 0.0-1.0. Could create beliefs that `context_update_belief` would refuse to update.

**Fix:** Added same guard at function entry.

**File:** `mcp/tools/context_store.py`

### bug_005: Misleading "superseded" Field Name

`context_crystallize` response had `superseded` containing input belief_ids that were promoted, not IDs of prior Commitments that were superseded. Misleading given the tool description mentions SUPERSEDES edges.

**Fix:** Renamed to `crystallized_belief_ids`.

**Files:** `mcp/tools/context_crystallize.py`, `tests/mcp/test_context_crystallize.py`

## Files Changed

### Source (7 files)
- `mcp/tools/context_belief_state.py` - silo validation, contradiction scoping
- `mcp/tools/context_update_belief.py` - silo validation
- `mcp/tools/context_crystallize.py` - silo validation, field rename
- `mcp/tools/context_store.py` - silo validation (belief branch), confidence validation
- `mcp/tools/context_recall.py` - preserve steps/reflections in projection
- `db/queries.py` - CRYSTALLIZE_TO_COMMITMENT row dedup, layer property
- `services/context.py` - int timestamp handling
- `custodian/fact_promotion.py` - read raw_confidence

### Tests (1 file)
- `tests/mcp/test_context_crystallize.py` - field rename

## Verification

```
just check      # pass (ruff + mypy)
just test       # 988 passed (unit), integration needs docker
```
