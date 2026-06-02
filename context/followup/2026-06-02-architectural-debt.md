# Architectural Debt: Brain Architecture

**Created:** 2026-06-02  
**Source:** Opus review of Phase 9 PR  
**Status:** PENDING

---

## 1. TX18 PROMOTE Not Wired Into Write Path

**Priority:** HIGH  
**Effort:** 30 min

**Current state:**
- `_check_corroboration()` in `sage/transactions.py:1864-1878` calculates corroboration count and returns `(count, should_promote)`
- The `promote()` function (lines 2409-2505) is fully implemented and converts Claim to Fact via `SET c:Fact`
- **Gap:** `store_claim()` never calls `promote()` when threshold is met

**Impact:** Claim nodes never become Facts, breaking the knowledge layer epistemology flow.

**Fix:**
```python
# In store_claim(), after _check_corroboration():
corroboration_count, should_promote = await _check_corroboration(store, str(node_id), silo_id)

if should_promote:
    await promote(store, str(node_id), silo_id, emit=False)
```

---

## 2. LLMResolver Stub (Deterministic Only)

**Priority:** LOW  
**Effort:** 15 min (config flag)

**Current state:**
- `LLMResolverStub` always returns DEFER
- Full `LLMResolver` class exists with complete implementation
- `ConsolidationWorker` defaults to `DeterministicResolver`

**Impact:** All conflicts resolve via scoring only. No merge/coexist decisions.

**Recommendation:** Accept for beta. Deterministic is correct and auditable.

**Mitigation:** Add config flag `CONSOLIDATION_USE_LLM=false` for opt-in:
```python
if settings.consolidation_use_llm and llm is not None:
    self._resolver = LLMResolver(llm)
else:
    self._resolver = DeterministicResolver()
```

**Trigger to prioritize:**
- User feedback on wrong supersession decisions
- Conflict volume >100/day where merge/coexist would help
- Customer request for human-in-the-loop review

---

## 3. Single Shared Queue (No Per-Silo Isolation)

**Priority:** LOW  
**Effort:** 1 hr (monitoring), 1 day (full partition)

**Current state:**
- All silos share `reactions:default` queue
- Silo isolation at task level via `silo_id` kwarg
- One worker pool serves all tenants

**Impact:** Noisy silo can delay reactions for others.

**Recommendation:** Defer for beta. Low risk with limited users.

**Mitigation:** Add queue depth monitoring per-silo:
- Alert if any silo >80% of queue volume
- Alert if queue depth >1000 sustained >5 min
- Alert if P95 reaction latency >5s

**Trigger to prioritize:**
- Multiple active silos with significant write volume
- Evidence of queue depth causing latency issues

---

---

## 4. Dead Code: Legacy MCP Tool Files

**Priority:** LOW  
**Effort:** 15 min

**Current state:**
- `mcp/tools/context_get.py`, `context_history.py`, `context_query.py`, `context_graph.py`, `context_crystallize.py`, `coerce.py` exist
- These are NOT registered in `registry.py` - only the 15 verb-based tools are live
- Files are orphaned dead code from pre-verb-surface refactor

**Fix:** Delete the orphaned files after confirming no imports.

---

## 5. ProposedBelief Cleanup Assets Still Active

**Priority:** LOW  
**Effort:** 30 min

**Current state:**
- TX11-13 (ProposedBelief write path) removed in Phase 7
- But `proposal_detection` and `proposal_cleanup` Dagster assets still registered
- `custodian/proposal_worker.py` still exists
- Daily cleanup schedule still runs

**Fix:** Remove orphaned assets and worker, or document why kept.

---

## Summary

| Item | Priority | Action |
|------|----------|--------|
| TX18 PROMOTE | HIGH | Fix before production |
| LLMResolver | LOW | Accept + flag for beta |
| Single queue | LOW | Defer + monitor for beta |
| Dead MCP tools | LOW | Delete orphaned files |
| ProposedBelief assets | LOW | Remove or document |
