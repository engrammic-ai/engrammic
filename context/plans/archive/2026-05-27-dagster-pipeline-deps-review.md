# Dagster Pipeline Dependencies Review

**Date:** 2026-05-27
**Status:** Complete

## Summary

Code review of the four SAGE pipeline schedules revealed several missing or incorrect asset dependency declarations. The data flows are conceptually sound, but Dagster's asset graph doesn't fully enforce the intended execution order in some cases.

## Findings by Pipeline

### 1. SAGE Custodian (ingestion, every 2h)

**Assets:** extraction → embedding → custodian_visit → claim_to_fact_promotion → custodian_finalize → clustering → proposal_detection

**Current deps:**
- `custodian_visit`: `deps=["extraction", "embedding"]`
- `claim_to_fact_promotion`: `deps=["custodian_visit"]`
- `custodian_finalize`: `deps=["custodian_visit"]`
- `clustering`: `deps=["custodian_finalize"]`
- `proposal_detection`: `deps=["clustering"]`

**Issue:** `custodian_finalize` and `claim_to_fact_promotion` both depend on `custodian_visit` but not on each other. Dagster could run them in parallel.

**Impact:** Findings may be created before claims are promoted to facts, meaning findings could reference unpromoted claims.

**Fix:** Add `claim_to_fact_promotion` to `custodian_finalize` deps:
```python
# custodian_finalize.py
deps=["custodian_visit", "claim_to_fact_promotion"]
```

---

### 2. SAGE Synthesizer (belief formation, hourly)

**Assets:** causal_transitivity → pattern_detection → llm_pattern_detection → belief_synthesis → belief_merge → chain_stitch

**Current deps:**
- `causal_transitivity`: `deps=["claim_to_fact_promotion"]`
- `pattern_detection`: `deps=["claim_to_fact_promotion"]`
- `llm_pattern_detection`: `deps=["pattern_detection"]`
- `belief_synthesis`: **no deps declared**
- `belief_merge`: **no deps declared**
- `chain_stitch`: `deps=["custodian_finalize"]`

**Issues:**

1. `belief_synthesis` has no deps - could run before/during pattern detection
2. `belief_merge` has no deps - could run before beliefs are synthesized
3. `llm_pattern_detection` deps `pattern_detection` but not `clustering` - if clusters don't exist, silently skips

**Impact:** In a fresh materialize-all run, assets could execute out of order. Currently works because schedule runs them sequentially by selection order, but this is implicit behavior not enforced by the graph.

**Fix:**
```python
# belief_synthesis.py
deps=["llm_pattern_detection"]

# belief_merge.py
deps=["belief_synthesis"]

# llm_pattern_detection.py (optional, for clarity)
deps=["pattern_detection", "clustering"]
```

---

### 3. SAGE Groundskeeper (heat/caching, hourly)

**Assets:** heat → edge_heat → heat_diffusion → prewarm_sweep

**Current deps:**
- `edge_heat`: `deps=["heat"]`
- `heat_diffusion`: `deps=["heat"]`
- `prewarm_sweep`: `deps=["heat_diffusion"]`

**Issues:**

1. `heat_diffusion` deps only `heat`, not `edge_heat` - both could run in parallel
2. `prewarm_sweep` queries `effective_heat` with no fallback to `heat_score` if diffusion is disabled

**Impact:** If diffusion uses edge weights for propagation, it may use stale edge heat values.

**Fix:**
```python
# heat_diffusion.py
deps=["heat", "edge_heat"]
```

**Optional:** Add `coalesce(n.effective_heat, n.heat_score, 0.0)` fallback in prewarm_sweep Cypher.

---

### 4. SAGE Validator (integrity checks, every 5m)

**Assets:** validator_contradiction, validator_stale_commitment, marker_cleanup

**Current deps:** None (all independent)

**Assessment:** Correct. These are independent maintenance tasks operating on different graph state. No changes needed.

**Minor note:** `marker_cleanup` could theoretically delete markers just written in the same run if TTLs are extremely short. Adding soft deps would be safer but not critical given current TTL values (days/weeks).

---

## Risk Assessment

| Pipeline | Severity | Likelihood | Notes |
|----------|----------|------------|-------|
| Custodian | Medium | Low | Only manifests on first run or after graph wipe |
| Synthesizer | Medium | Low | Same - implicit ordering currently works |
| Groundskeeper | Low | Low | Only if edge weights affect diffusion |
| Validator | None | N/A | Correctly independent |

## Resolution

**Option A selected:** Fixed all 5 assets.

### Changes Made

1. `custodian_finalize.py`: `deps=["custodian_visit"]` → `deps=["custodian_visit", "claim_to_fact_promotion"]`
2. `belief_synthesis.py`: no deps → `deps=["llm_pattern_detection"]`
3. `belief_merge.py`: no deps → `deps=["belief_synthesis"]`
4. `llm_pattern_detection.py`: `deps=["pattern_detection"]` → `deps=["pattern_detection", "clustering"]`
5. `heat_diffusion.py`: `deps=["heat"]` → `deps=["heat", "edge_heat"]`

Also fixed stale test assertions in `tests/test_schedules.py` (schedule count 10→12, removed reference to renamed `tag_maintenance_schedule`).
