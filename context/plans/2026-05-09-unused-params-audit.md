# Unused Parameters Audit

**Date:** 2026-05-09  
**Context:** Discovered during custodian identity split implementation

---

## Summary

Audit of function parameters that are declared but not used, identified via ruff ARG001/ARG002 rules and underscore-prefix conventions.

---

## Categories

### 1. Framework Contract Parameters

These parameters are required by framework signatures but not used in implementation. Correct as-is.

| File | Line | Function | Parameter | Framework |
|------|------|----------|-----------|-----------|
| `api/metrics.py` | 103 | `metrics_endpoint` | `_request` | FastAPI |
| `pipelines/resources.py` | 93 | `teardown_after_execution` | `_context` | Dagster |
| `pipelines/resources.py` | 120 | `teardown_after_execution` | `_context` | Dagster |
| `pipelines/resources.py` | 164 | `teardown_after_execution` | `_context` | Dagster |
| `pipelines/resources.py` | 189 | `teardown_after_execution` | `_context` | Dagster |
| `pipelines/resources.py` | 206 | `teardown_after_execution` | `_context` | Dagster |
| `api/routes/skills.py` | 23 | `list_skills` | `credentials` | FastAPI DI |
| `api/routes/skills.py` | 30 | `get_skill` | `credentials` | FastAPI DI |

### 2. Dagster Dependency Markers

These are `dg.Nothing` parameters that declare asset dependencies without passing data. Correct as-is.

| File | Line | Parameter |
|------|------|-----------|
| `pipelines/assets/causal.py` | 126 | `claim_to_fact_promotion` |
| `pipelines/assets/custodian_finalize.py` | 46 | `custodian_visit` |
| `pipelines/assets/clustering.py` | 46 | `custodian_finalize` |
| `pipelines/assets/proposal_detection.py` | 35 | `clustering` |
| `pipelines/assets/pattern_detection.py` | 45 | `claim_to_fact_promotion` |
| `pipelines/assets/custodian_visit.py` | 63 | `extraction` |
| `pipelines/assets/custodian_visit.py` | 64 | `embedding` |
| `pipelines/assets/llm_pattern_detection.py` | 70 | `pattern_detection` |
| `pipelines/assets/fact_promotion.py` | 67 | `custodian_visit` |
| `pipelines/assets/chain_stitch.py` | 36 | `custodian_finalize` |

### 3. Forward Compatibility / Reserved

These parameters are intentionally accepted for API stability or future use. Correct as-is.

| File | Line | Function | Parameter | Note |
|------|------|----------|-----------|------|
| `utils/json.py` | 16 | `dumps` | `**_kwargs` | stdlib-compatible signature |
| `utils/json.py` | 21 | `loads` | `**_kwargs` | stdlib-compatible signature |
| `custodian/promotion.py` | 146 | `find_promotion_candidates` | `org_id` | Reserved for org isolation |

### 4. Protocol Implementation

Parameters required by protocol/interface but not used in specific implementation.

| File | Line | Function | Parameter | Note |
|------|------|----------|-----------|------|
| `custodian/identities/triggers/async_batch.py` | 24 | `enqueue` | `event_type` | CustodianTrigger protocol; now wired via context.py |

### 5. Needs Investigation

These parameters appear to be bugs or incomplete implementations.

#### 5.1 `max_depth` in `services/context.py:760`

```python
async def provenance(
    self,
    silo_id: str,
    node_id: str,
    max_depth: int = 10,  # noqa: ARG002
) -> ProvenanceResult:
```

**Issue:** Parameter is accepted but never passed to the Cypher query.

**Investigation:** The query `PROVENANCE_CHAIN` in `db/queries.py:416` has `*1..10` hardcoded:
```cypher
MATCH path = (start ...)-[:DERIVED_FROM|...]*1..10]->(source)
```

Cypher does not support parameterized path lengths directly. Options:
1. **Keep as-is** with better comment explaining the 10 is hardcoded
2. **Remove parameter** since it's not actually configurable without query generation
3. **Generate query** with depth embedded (adds complexity)

**Recommendation:** Option 1 - improve the comment to explain limitation.

#### 5.2 `name` in `mcp/tools/context_admin.py:244` - FALSE POSITIVE

```python
name: str | None = None,  # noqa: ARG001
```

**Issue:** Parameter was marked as unused but IS actually used.

**Investigation:** The `name` parameter IS used by:
- `temporal_query` action (line 295): `query=name or ""`
- `partial_revise` action (line 337): validates `name` is provided, uses as revision_note

**Resolution:** Removed the incorrect `noqa: ARG001` comment. The parameter is correctly used.

---

## Action Items

- [ ] Investigate `max_depth` in provenance() - check if query should support depth limiting
- [ ] Investigate `name` in context_admin - determine intended purpose
- [ ] Add inline comments to reserved params explaining future use

---

## Notes

All other suppressions are justified by framework requirements or explicit forward-compatibility needs. The codebase correctly uses:
- Underscore prefix (`_param`) for framework-required unused params
- `# noqa: ARG001/ARG002` with explanatory comments for most cases
