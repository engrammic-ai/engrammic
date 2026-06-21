---
phase: sage-phase-c-synthesizer
reviewed: 2026-06-21T14:30:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - src/context_service/db/queries.py
  - src/context_service/pipelines/definitions.py
  - src/context_service/pipelines/jobs/__init__.py
  - src/context_service/pipelines/jobs/synthesizer_job.py
  - src/context_service/pipelines/schedules.py
  - src/context_service/reactions/events.py
  - src/context_service/reactions/tasks.py
  - src/context_service/sage/__init__.py
  - src/context_service/sage/transactions.py
  - tests/pipelines/test_synthesizer_job.py
  - tests/sage/test_belief_flow.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# PR #69: SAGE Phase C - Simplify Synthesizer Code Review

**Reviewed:** 2026-06-21
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

The PR introduces a new scheduled Dagster job for vector-based synthesis (`sage_synthesizer_job`) and removes dead cluster-based synthesis code. The new synthesizer job is correctly wired up to the Dagster definitions with a 15-minute schedule. However, several issues were found:

1. **Critical:** `revise_belief` (TX5) still depends on cluster-based infrastructure that should be deprecated
2. **Warning:** Test coverage for the new synthesizer is insufficient
3. **Warning:** Skipped test without a remediation plan
4. **Warning:** Dead code left in `promote()` function

## Critical Issues

### CR-01: revise_belief still depends on deprecated cluster infrastructure

**File:** `src/context_service/sage/transactions.py:1860-2076`
**Issue:** The `revise_belief` function (TX5) still relies on cluster-based synthesis paths that Phase C intends to remove. It reads `source_cluster_id` from beliefs, calls `GET_CLUSTER_FOR_SYNTHESIS`, `GET_FACTS_IN_CLUSTER`, and `RELEASE_CLUSTER_LOCK` queries. This creates an inconsistency where:
- New beliefs are created via `synthesize_from_facts()` without clusters
- Existing beliefs being revised still expect `source_cluster_id` to exist
- The function will fail for any belief created by the new v2 synthesizer (which doesn't set `source_cluster_id`)

**Fix:** Either:
1. Update `revise_belief` to work with v2 beliefs (trace SYNTHESIZED_FROM edges to facts instead of using cluster_id), or
2. Deprecate `revise_belief` entirely if v2 synthesis handles staleness differently, or
3. Document this as a known limitation (v2 beliefs cannot be revised until a follow-up PR)

```python
# Option 1 sketch: Replace cluster-based fact lookup with edge traversal
async def revise_belief_v2(store, belief_id, silo_id, llm, ...):
    # Fetch facts via SYNTHESIZED_FROM edges instead of cluster
    facts_result = await store.execute_query(
        """
        MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
              -[:SYNTHESIZED_FROM]->(f:Fact {state: 'ACTIVE'})
        RETURN f.id AS fact_id, f.content AS content, f.confidence AS confidence
        """,
        {"belief_id": belief_id, "silo_id": silo_id},
    )
    # ... rest of logic without cluster locking
```

## Warnings

### WR-01: Insufficient test coverage for synthesizer_job

**File:** `tests/pipelines/test_synthesizer_job.py:1-45`
**Issue:** The test file only verifies structural wiring (job name, op resources, registration). There are no tests for:
- `run_synthesis_for_silo()` behavior with mock stores
- Error handling paths (line 109-120)
- The disabled tier early return (line 137-139)
- Integration with `synthesize_from_facts()`

**Fix:** Add unit tests for the core synthesis logic:

```python
@pytest.mark.asyncio
async def test_run_synthesis_for_silo_no_candidates():
    """Test that empty candidates returns zero counts."""
    mock_store = AsyncMock()
    mock_store.execute_query = AsyncMock(return_value=[])  # No candidates
    mock_llm = AsyncMock()
    settings = SynthesisSettings(tier="standard", ...)
    
    result = await run_synthesis_for_silo(mock_store, "test-silo", mock_llm, settings, mock_log)
    assert result == {"synthesized": 0, "skipped": 0, "errors": 0}

@pytest.mark.asyncio
async def test_run_synthesis_for_silo_handles_errors():
    """Test that synthesis errors are counted, not propagated."""
    # ... test exception handling in the for loop
```

### WR-02: Skipped test without remediation plan

**File:** `tests/sage/test_belief_flow.py:275`
**Issue:** `test_creates_new_belief_on_content_change` is skipped with reason "Mock data expects old cluster-based synthesis; revise_belief internals changed". This is correct given CR-01, but there's no follow-up issue or TODO tracking when this will be fixed.

**Fix:** Either:
1. Create a tracking issue for fixing the test when `revise_belief` is updated
2. Add a TODO comment with the issue number
3. Delete the test if `revise_belief` will be deprecated

### WR-03: Dead code in promote() function

**File:** `src/context_service/sage/transactions.py:3075-3079`
**Issue:** The `promote()` function now has an empty events list that is iterated over and emitted. This is dead code that will never execute anything:

```python
events: list[ReactionEvent] = []

if emit:
    for event in events:  # Never executes
        await emit_reaction(event)
```

**Fix:** Remove the dead emit logic since there are no events to emit after removing `UPDATE_CLUSTER_MEMBERSHIP`:

```python
events: list[ReactionEvent] = []

logger.debug(
    "promote_complete",
    ...
)

return result, events
```

## Info

### IN-01: Deprecated synthesize() function still exported

**File:** `src/context_service/sage/transactions.py:411-614`
**Issue:** The old cluster-based `synthesize()` function is still defined (with a deprecation warning) but no longer exported from `sage/__init__.py`. The function body remains ~200 lines of code. Consider removing entirely or adding a note about when it will be removed.

**Fix:** If no external callers remain, delete the function entirely. If keeping for backwards compatibility, add a removal timeline in the docstring.

### IN-02: Remaining cluster query stubs could be cleaned up

**File:** `src/context_service/db/queries.py:1405-1408`
**Issue:** Four cluster-related query stubs remain:
- `LIST_CLUSTERS`
- `GET_CLUSTER_FOR_SYNTHESIS`
- `RELEASE_CLUSTER_LOCK`
- `UPDATE_CLUSTER_AFTER_SYNTHESIS`

These are used by the deprecated `synthesize()` and `revise_belief()`. Once CR-01 is addressed, these can be removed.

**Fix:** Track for removal in a follow-up PR after `revise_belief` is updated.

---

_Reviewed: 2026-06-21T14:30:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
