# Wiring Gaps Review

**Date**: 2026-05-04  
**Updated**: 2026-05-04  
**Scope**: Full codebase scan for implemented-but-unwired features

---

## Critical: Runtime Crash Bugs

~~All fixed in commit 369c50e~~

### 1. `context_admin.py:248` - Invalid `mode` parameter

**FIXED** - Was already corrected before review (uses `relationship_types` now)

### 2. `context_recall.py:32-37` - Undeclared reflection parameters

**FIXED** - Reflection params added to `_context_get` signature with full implementation

---

## High: Complete Features Not Wired

### Extraction Filter Pipeline

**FIXED** in commit 369c50e - FilterOrchestrator now wired in Dagster extraction asset.

| Component | Location | Status |
|-----------|----------|--------|
| `FilterOrchestrator` | `extraction/filter/orchestrator.py` | **WIRED** |
| `WikidataRule` | `extraction/filter/wikidata.py` | **WIRED** |
| `LLMClassifierRule` | `extraction/filter/llm_classifier.py` | **WIRED** |
| `resolve_alias()` | `extraction/alias_lookup.py` | **WIRED** via AliasCache in extraction |

Config: `config/extraction_filter.yaml`

### Engine Layer

**FIXED** in commits 4c62850, fa7cd3f

| Function | Location | Status |
|----------|----------|--------|
| `detect_overlapping_beliefs()` | `engine/synthesis.py` | **WIRED** via belief_merge asset |
| `merge_beliefs()` | `engine/synthesis.py` | **WIRED** via belief_merge asset |
| `check_belief_coverage()` | `engine/synthesis.py` | **WIRED** via belief_synthesis guard |
| `split_belief()` | `engine/revision.py` | **WIRED** via partial_revise MCP action |
| `partial_revise_belief()` | `engine/revision.py` | **WIRED** via partial_revise MCP action |
| `flag_cascade()` | `engine/revision.py` | **WIRED** via partial_revise MCP action |
| `get_cascade_pending()` | `engine/revision.py` | **WIRED** via cascade_review sensor |
| `clear_cascade_pending()` | `engine/revision.py` | **WIRED** via cascade_review asset |

### ContextService Methods

**FIXED** in commit 4c62850

| Method | Status |
|--------|--------|
| `provenance()` | **WIRED** via context_admin action |
| `temporal_query()` | **WIRED** via context_admin action |
| `belief_history()` | **WIRED** via context_admin action |
| `history()` | Already wired via context_admin |
| `remember()`, `get()`, `query()`, `link()` | Already wired |
| `assert_claim()`, `commit_belief()`, `reason()` | Already wired via context_store |
| `reflect()`, `get_reflections()` | Already wired via context_store/recall |

---

## Medium: Dagster Assets Without Triggers

**FIXED** in commits 4c62850, fa7cd3f

| Asset | Status |
|-------|--------|
| `causal_transitivity` | **WIRED** via causal_transitivity_sensor |
| `causal_tombstone` | **WIRED** via causal_tombstone_job (manual) |
| `llm_pattern_detection` | **WIRED** via llm_pattern_detection_schedule |
| `chain_stitch` | **WIRED** via chain_stitch_sensor |

### Placeholder Sensor

`summarization_retry_sensor` **REMOVED** from registration (placeholder until resummarization asset exists)

---

## Low: Cleanup Items

**FIXED** in commit 369c50e

| Item | Location | Status |
|------|----------|--------|
| `register()` stubs | `mcp/tools/context_get.py`, etc. | **REMOVED** |
| Tool count log | `mcp/server.py:188` | **FIXED** (now logs `tools=4`) |

---

## Remaining Work

1. ~~Crash bugs~~ **DONE**
2. ~~Filter pipeline wiring~~ **DONE**
3. ~~Cleanup dead code~~ **DONE**
4. ~~Service method exposure~~ **DONE**
5. ~~Dagster asset triggers~~ **DONE**
6. ~~Engine layer functions~~ **DONE**
7. ~~resolve_alias()~~ **DONE**

---

## Summary

**All wiring gaps addressed.** Commits: 369c50e, 4c62850, fa7cd3f, 10dbec7, 95ee583

No remaining items.
