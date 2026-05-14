# SAGE Job Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace 8 Dagster sensors with 3 SAGE scheduled jobs for predictable, consolidated pipeline execution.

**Architecture:** Refactor `schedules.py` to define three SAGE schedules (custodian, synthesizer, groundskeeper) that query for silos with pending work and trigger partition runs. Remove replaced sensors, keep poison_queue and cascade_review.

**Tech Stack:** Dagster schedules, Memgraph queries, Python async

---

## File Structure

**Modify:**
- `src/context_service/pipelines/schedules.py` - Replace existing pipeline schedules with SAGE schedules
- `src/context_service/pipelines/sensors/__init__.py` - Remove replaced sensors from exports
- `src/context_service/pipelines/definitions.py` - No changes needed (schedules auto-imported)

**Delete:**
- `src/context_service/pipelines/sensors/document_arrival.py`
- `src/context_service/pipelines/sensors/belief_synthesis.py`
- `src/context_service/pipelines/sensors/belief_merge.py`
- `src/context_service/pipelines/sensors/causal_chain_sensor.py`
- `src/context_service/pipelines/sensors/confidence_drift.py`
- `src/context_service/pipelines/sensors/session_autoclose.py`
- `src/context_service/pipelines/sensors/synthesizer_sensor.py`

**Keep (no changes):**
- `src/context_service/pipelines/sensors/poison_queue_sensor.py`
- `src/context_service/pipelines/sensors/cascade_review.py`

---

### Task 1: Add SAGE pending work queries to schedules.py

**Files:**
- Modify: `src/context_service/pipelines/schedules.py:24-40`

- [ ] **Step 1: Add pending work query constants**

Add after the existing `_LIST_ACTIVE_SILOS` query (line 24):

```python
_LIST_ACTIVE_SILOS = """
MATCH (d:Document)
RETURN DISTINCT d.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_CUSTODIAN_WORK = """
MATCH (d:Document)
WHERE d.processed_at IS NULL
   OR d.embedded_at IS NULL
RETURN DISTINCT d.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_SYNTHESIZER_WORK = """
MATCH (c:Cluster)
WHERE NOT EXISTS { MATCH (c)<-[:SYNTHESIZED_FROM]-(:Belief) }
RETURN DISTINCT c.silo_id AS silo_id
UNION
MATCH (b:Belief)
WHERE b.status IS NULL OR b.status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH b.silo_id AS silo_id, subject, count(b) AS cnt
WHERE cnt >= 2
RETURN DISTINCT silo_id
"""

_SILOS_WITH_PENDING_GROUNDSKEEPER_WORK = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
  AND (n.heat_updated_at IS NULL
       OR n.heat_updated_at < datetime() - duration('PT1H'))
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 50
"""
```

- [ ] **Step 2: Add query helper functions**

Add after the query constants:

```python
def _fetch_silos_with_pending_work(
    memgraph: MemgraphResource,
    query: str,
) -> list[str]:
    """Fetch silo IDs that have pending work based on query."""
    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(query, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    return asyncio.run(_run())
```

- [ ] **Step 3: Verify file is syntactically correct**

Run: `python -m py_compile src/context_service/pipelines/schedules.py`
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat(sage): add pending work queries for SAGE schedules"
```

---

### Task 2: Define sage_custodian_schedule

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Replace custodian_pipeline_schedule with sage_custodian_schedule**

Replace the `custodian_pipeline_schedule` function (around line 47-66) with:

```python
@dg.schedule(
    cron_schedule="*/10 * * * *",
    name="sage_custodian_schedule",
    target=dg.AssetSelection.assets(
        "extraction",
        "embedding",
        "custodian_visit",
        "claim_to_fact_promotion",
        "custodian_finalize",
        "clustering",
        "proposal_detection",
    ),
    description="SAGE Custodian (10 min): ingestion pipeline - extraction through proposal detection.",
    execution_timezone="UTC",
)
def sage_custodian_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """SAGE Custodian: ingestion pipeline for silos with pending documents."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_CUSTODIAN_WORK)
    if not silo_ids:
        silo_ids = _fetch_silo_ids(memgraph)
    
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"sage_custodian:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"sage_job": "custodian", "dagster/concurrency_key": silo_id},
        )
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile src/context_service/pipelines/schedules.py`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat(sage): add sage_custodian_schedule (10 min ingestion pipeline)"
```

---

### Task 3: Define sage_synthesizer_schedule

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Replace knowledge_pipeline_schedule with sage_synthesizer_schedule**

Replace `knowledge_pipeline_schedule` (around line 68-92) with:

```python
@dg.schedule(
    cron_schedule="*/30 * * * *",
    name="sage_synthesizer_schedule",
    target=dg.AssetSelection.assets(
        "causal_transitivity",
        "pattern_detection",
        "llm_pattern_detection",
        "belief_synthesis",
        "belief_merge",
        "chain_stitch",
    ),
    description="SAGE Synthesizer (30 min): belief formation - facts to wisdom.",
    execution_timezone="UTC",
)
def sage_synthesizer_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """SAGE Synthesizer: belief formation for silos with pending synthesis work."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_SYNTHESIZER_WORK)
    if not silo_ids:
        silo_ids = _fetch_silo_ids(memgraph)
    
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"sage_synthesizer:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"sage_job": "synthesizer", "dagster/concurrency_key": silo_id},
        )
```

- [ ] **Step 2: Remove clustering_pipeline_schedule**

Delete the `clustering_pipeline_schedule` function entirely (was around line 94-117) - its assets are now in sage_custodian and sage_synthesizer.

- [ ] **Step 3: Verify syntax**

Run: `python -m py_compile src/context_service/pipelines/schedules.py`
Expected: No output (success)

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat(sage): add sage_synthesizer_schedule (30 min belief formation)"
```

---

### Task 4: Define sage_groundskeeper_schedule

**Files:**
- Modify: `src/context_service/pipelines/schedules.py`

- [ ] **Step 1: Replace heat_pipeline_schedule with sage_groundskeeper_schedule**

Replace `heat_pipeline_schedule` (around line 119-138) with:

```python
@dg.schedule(
    cron_schedule="*/15 * * * *",
    name="sage_groundskeeper_schedule",
    target=dg.AssetSelection.assets(
        "heat",
        "edge_heat",
        "heat_diffusion",
        "prewarm_sweep",
    ),
    description="SAGE Groundskeeper (15 min): heat and maintenance.",
    execution_timezone="UTC",
)
def sage_groundskeeper_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """SAGE Groundskeeper: heat and maintenance for silos with stale scores."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_GROUNDSKEEPER_WORK)
    if not silo_ids:
        silo_ids = _fetch_silo_ids(memgraph)
    
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"sage_groundskeeper:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"sage_job": "groundskeeper", "dagster/concurrency_key": silo_id},
        )
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile src/context_service/pipelines/schedules.py`
Expected: No output (success)

- [ ] **Step 3: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "feat(sage): add sage_groundskeeper_schedule (15 min heat/maintenance)"
```

---

### Task 5: Update all_schedules export list

**Files:**
- Modify: `src/context_service/pipelines/schedules.py:280-310`

- [ ] **Step 1: Update all_schedules list**

Replace the `all_schedules` list and `__all__` at the end of the file:

```python
all_schedules: list[Any] = [
    # SAGE pipelines
    sage_custodian_schedule,
    sage_synthesizer_schedule,
    sage_groundskeeper_schedule,
    # Maintenance (kept separate)
    reasoning_compaction_schedule,
    retention_schedule,
    auto_tagging_schedule,
    tag_maintenance_schedule,
    reconciliation_gc_schedule,
    proposal_cleanup_schedule,
    groundskeeper_gc_schedule,
]

__all__ = [
    "all_schedules",
    "sage_custodian_schedule",
    "sage_synthesizer_schedule",
    "sage_groundskeeper_schedule",
    "reasoning_compaction_schedule",
    "retention_schedule",
    "auto_tagging_schedule",
    "tag_maintenance_schedule",
    "reconciliation_gc_schedule",
    "proposal_cleanup_schedule",
    "groundskeeper_gc_schedule",
]
```

- [ ] **Step 2: Update module docstring**

Replace the docstring at the top of the file:

```python
"""Dagster schedule definitions for context-service.

SAGE (Synthesis, Aggregation, and Graph Evolution) schedules:
- sage_custodian_schedule: ingestion pipeline (10 min)
- sage_synthesizer_schedule: belief formation (30 min)
- sage_groundskeeper_schedule: heat and maintenance (15 min)

Maintenance schedules (independent):
- reasoning_compaction_schedule: hourly
- retention_schedule: daily 03:00
- auto_tagging_schedule: every 30 min
- tag_maintenance_schedule: daily 03:00
- reconciliation_gc_schedule: every 15 min
- proposal_cleanup_schedule: daily 06:00
- groundskeeper_gc_schedule: nightly 01:00
"""
```

- [ ] **Step 3: Run linter**

Run: `uv run ruff check src/context_service/pipelines/schedules.py --fix`
Expected: All checks passed (or auto-fixed)

- [ ] **Step 4: Run type checker**

Run: `uv run mypy src/context_service/pipelines/schedules.py`
Expected: Success: no issues found

- [ ] **Step 5: Commit**

```bash
git add src/context_service/pipelines/schedules.py
git commit -m "refactor(sage): update schedule exports and docstring"
```

---

### Task 6: Remove replaced sensors

**Files:**
- Modify: `src/context_service/pipelines/sensors/__init__.py`
- Delete: 7 sensor files

- [ ] **Step 1: Update sensors/__init__.py**

Replace entire file contents:

```python
"""Dagster sensors for context-service.

Most sensors have been consolidated into SAGE schedules.
Remaining sensors handle edge cases not suitable for scheduled execution.
"""

from typing import Any

from context_service.pipelines.sensors.cascade_review import cascade_review_sensor
from context_service.pipelines.sensors.poison_queue_sensor import poison_queue_sensor

all_sensors: list[Any] = [
    poison_queue_sensor,
    cascade_review_sensor,
]
```

- [ ] **Step 2: Delete replaced sensor files**

```bash
git rm src/context_service/pipelines/sensors/document_arrival.py
git rm src/context_service/pipelines/sensors/belief_synthesis.py
git rm src/context_service/pipelines/sensors/belief_merge.py
git rm src/context_service/pipelines/sensors/causal_chain_sensor.py
git rm src/context_service/pipelines/sensors/confidence_drift.py
git rm src/context_service/pipelines/sensors/session_autoclose.py
git rm src/context_service/pipelines/sensors/synthesizer_sensor.py
```

- [ ] **Step 3: Verify imports work**

Run: `python -c "from context_service.pipelines.sensors import all_sensors; print(len(all_sensors))"`
Expected: `2`

- [ ] **Step 4: Commit**

```bash
git add src/context_service/pipelines/sensors/__init__.py
git commit -m "refactor(sage): remove sensors replaced by SAGE schedules

Removed: document_arrival, belief_synthesis, belief_merge,
causal_chain, confidence_drift, session_autoclose, synthesizer_threshold

Kept: poison_queue (error recovery), cascade_review (future validator)"
```

---

### Task 7: Run full test suite

**Files:**
- None (verification only)

- [ ] **Step 1: Run linter on pipelines module**

Run: `uv run ruff check src/context_service/pipelines/ --fix`
Expected: All checks passed

- [ ] **Step 2: Run type checker on pipelines module**

Run: `uv run mypy src/context_service/pipelines/`
Expected: Success: no issues found

- [ ] **Step 3: Run pipeline-related tests**

Run: `uv run pytest tests/ -k "pipeline or schedule or sensor" -v --tb=short`
Expected: All tests pass (some may need adjustment if they reference removed sensors)

- [ ] **Step 4: Run full check**

Run: `just check`
Expected: All checks pass

- [ ] **Step 5: Commit any test fixes if needed**

```bash
git add -A
git commit -m "test: fix tests for SAGE schedule consolidation"
```

---

### Task 8: Final verification and push

**Files:**
- None (verification only)

- [ ] **Step 1: Verify Dagster can load definitions**

Run: `uv run python -c "from context_service.pipelines.definitions import defs; print(f'Schedules: {len(defs.schedules)}, Sensors: {len(defs.sensors)}')" `
Expected: `Schedules: 10, Sensors: 2` (3 SAGE + 7 maintenance schedules, 2 sensors)

- [ ] **Step 2: Review git log**

Run: `git log --oneline -10`
Expected: See all SAGE-related commits

- [ ] **Step 3: Push to remote**

Run: `git push origin feat/heat-diffusion`
Expected: Push succeeds

---

## Post-Implementation Notes

After deploying:
1. Monitor Dagster UI for SAGE schedule runs
2. Verify silos are being processed at expected cadences
3. Check that pending work queries correctly identify work
4. If queries miss edge cases, refine them based on production data
