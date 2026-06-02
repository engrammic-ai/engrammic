# Architectural Debt: Brain Architecture

**Created:** 2026-06-02  
**Source:** Opus review of Phase 9 PR  
**Status:** RESOLVED

---

## 1. TX18 PROMOTE Not Wired Into Write Path

**Priority:** HIGH  
**Status:** DONE

`store_claim()` now calls `promote()` when corroboration threshold is met.
Added error handling for race conditions per Opus review.

---

## 2. LLMResolver Config Flag

**Priority:** LOW  
**Status:** DONE (config only)

Added `ConsolidationConfig.use_llm_resolver` flag in settings (default: false).
Not wired to task yet - LLMResolver.resolve is async but Resolver protocol expects sync.
Deterministic is correct for beta; wire LLM when async resolver support is added.

---

## 3. Single Shared Queue (No Per-Silo Isolation)

**Priority:** LOW  
**Status:** NO ACTION NEEDED

Queue depth monitoring already exists via `reaction_queue_depth_sensor` Dagster sensor.
Per-silo depth tracking is implemented. Defer queue partitioning until needed.

---

## 4. Dead Code: Legacy MCP Tool Files

**Priority:** LOW  
**Status:** DONE (corrected scope)

**Original doc claimed 6 files orphaned - investigation found only 1:**
- `context_history.py` - DELETED (was orphaned)
- `context_get.py`, `context_query.py`, `context_graph.py`, `context_crystallize.py`, `coerce.py` - KEPT (actively imported by registered tools)

---

## 5. ProposedBelief Cleanup Assets

**Priority:** LOW  
**Status:** NO ACTION NEEDED (not orphaned)

**Original doc claimed assets were orphaned - investigation found they are active:**
- `proposal_detection` asset - registered, used by custodian
- `proposal_cleanup` asset - registered, runs daily at 06:00 UTC
- `custodian/proposal_worker.py` - actively called by proposal_detection
- TX11-13 were never implemented (not removed) - ProposedBelief uses direct queries

ProposedBelief is a wisdom-layer staging node for weak synthesis candidates.
The cleanup system is architecturally correct and actively used.

---

## Summary

| Item | Priority | Resolution |
|------|----------|------------|
| TX18 PROMOTE | HIGH | Fixed + error handling |
| LLMResolver | LOW | Config flag added |
| Single queue | LOW | Already monitored |
| Dead MCP tools | LOW | 1 file deleted (not 6) |
| ProposedBelief assets | LOW | Not orphaned, kept |
