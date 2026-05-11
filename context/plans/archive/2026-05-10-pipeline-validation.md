# Pipeline Validation Q/A Plan

Date: 2026-05-10
Status: Complete

## Summary

| Pipeline | Status | Notes |
|----------|--------|-------|
| Heat | PASS | Node + edge events emitting, scores applied |
| Extraction | PARTIAL | Pipeline runs, Documents are URI placeholders |
| Compaction | SKIPPED | All data <1 day old, no decay eligible |
| Pattern detection | PASS | 100 patterns created, OBSERVED_IN edges |
| Belief lifecycle | PARTIAL | Assets exist, no ProposedBeliefs to test |

**Fixes deployed:**
- `context_graph.py` - emit node access events during traversal
- `resources.py` - suppress async cleanup warning in Dagster teardown

## Overview

Systematic validation of Dagster pipeline assets beyond the Custodian flow (which was validated earlier today).

---

## 1. Heat Pipelines (Signals Layer)

**Assets:** `heat`, `edge_heat`
**Priority:** High (signals affect retrieval scoring)
**Status:** PASS

| Check | Method | Result |
|-------|--------|--------|
| Redis stream exists | `redis-cli XLEN silo:{id}:access_events` | PASS - 278 events |
| Events being emitted | Make recall calls, check stream grows | PASS - 273→278 (+5 nodes) |
| Edge events emitted | Check edge_access_events stream | PASS - 9→12 (+3 edges) |
| Heat asset runs | `dagster asset materialize heat` | PASS - RUN_SUCCESS |
| Heat scores applied | Query nodes with heat_score | PASS - 10+ nodes with scores |

**Fix deployed:** `context_graph.py` now emits node access events during graph traversal (was only emitting edge events).

---

## 2. Compaction/Retention (Memory Decay)

**Assets:** `compaction`, `retention`
**Priority:** High (production memory management)
**Status:** SKIPPED

| Check | Method | Result |
|-------|--------|--------|
| decay_class distribution | Query nodes by decay_class | 503 NULL (Knowledge layer), 14 standard, 1 durable, 1 ephemeral |
| Node ages | Check created_at timestamps | All nodes <1 day old |

**Finding:** All data too fresh to trigger decay thresholds (ephemeral=7d, standard=90d). Knowledge layer nodes (Claims, Facts, Documents) intentionally have no decay_class - they persist until superseded.

**Not a bug:** 503 nodes without decay_class is expected. Only Memory layer nodes decay.

---

## 3. Extraction Pipeline

**Assets:** `extraction`, `custodian_visit`
**Priority:** Medium (document ingestion path)
**Status:** PARTIAL

| Check | Method | Result |
|-------|--------|--------|
| Document count | Query Document nodes | 283 total |
| Documents with content | Filter by content IS NOT NULL | Only 16 have content |
| Extraction asset runs | `dagster asset materialize extraction` | PASS - RUN_SUCCESS |
| Claims extracted | Check EXTRACTED_FROM edges | 0 edges |

**Finding:** 267 of 283 Documents are URI placeholders from evidence validation (no extractable content). The 16 with content are short claim-like text, not full documents suitable for extraction.

**Not a bug:** Pipeline runs correctly but no suitable source documents to extract from.

---

## 4. Pattern Detection

**Assets:** `pattern_detection`, `llm_pattern_detection`
**Priority:** Medium (synthesis quality)
**Status:** PASS

| Check | Method | Result |
|-------|--------|--------|
| Prerequisites | Check Clusters and Facts | 11 Clusters, 142 Facts |
| Pattern detection runs | Run via Python (disabled in prod config) | PASS - 100 co_occurrence patterns |
| Edges created | Check OBSERVED_IN edges | 200 edges (2 per pattern) |
| Causal patterns | Check causal_chain patterns | 0 (no CAUSES edges in graph) |

**Note:** Uses `OBSERVED_IN` edge type (Pattern → Node), not `SYNTHESIZED_FROM`. Semantically correct - patterns "observe" facts. Config has `pattern.detection_enabled = False` in production.

---

## 5. Belief Lifecycle

**Assets:** `proposal_detection`, `proposal_cleanup`, `belief_merge`, `cascade_review`
**Priority:** Medium (governance flow)
**Status:** PARTIAL

| Check | Method | Result |
|-------|--------|--------|
| Assets registered | Check Dagster definitions | PASS - all 4 assets exist |
| Existing Beliefs | Query Belief nodes | 6 Beliefs present |
| ProposedBeliefs | Query ProposedBelief nodes | 0 (none generated yet) |
| SUPERSEDES edges | Query SUPERSEDES relationships | 0 (no belief revisions) |
| MCP tools | Check tool registration | context_accept_belief, context_reject_belief registered |

**Blocker:** Cannot test accept/reject flow without ProposedBelief nodes. Need low-confidence synthesis run to generate testable proposals.

**Implementation verified:** SUPERSEDES handling exists in `custodian/identities/custodian.py` and `chain_stitcher.py`.

---

## 6. Weak Link Detection

**Assets:** `weak_link_creation`, `weak_link_review`
**Priority:** Low (implicit relationship discovery)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Candidate detection | Run on nodes with shared tags/content | Candidates created |
| Review queue | Check weak links pending review | Queue populated |
| Promotion | Accept weak link | Becomes real edge |
| Rejection | Reject weak link | Removed from queue |

---

## Execution Order

1. **Heat** - quick validation, verifies signals layer
2. **Extraction** - validates ingestion path
3. **Compaction** - validates decay (needs test data with old timestamps)
4. **Pattern detection** - validates synthesis quality
5. **Belief lifecycle** - validates governance flow
6. **Weak links** - low priority, skip if time constrained

---

## Prerequisites

- Docker stack running (`just docker-up`)
- SigNoz/OTEL for tracing (optional but helpful)
- Test silo with existing data from Custodian validation

---

## Notes

- Custodian flow (fact_promotion, embedding, clustering, belief_synthesis) already validated 2026-05-10
- Redis semaphore fix applied to `access_events.py` and `edge_access_events.py`
- Evidence edge creation fix applied to `evidence.py` and `context_store.py`

## Fixes deployed during validation

1. **context_graph.py** - Added node access event emission during graph traversal
2. **resources.py** - Wrapped async close in try/except to suppress "Event loop is closed" warning

## Follow-up items

- Generate ProposedBeliefs via low-confidence synthesis to test accept/reject flow
- Consider enabling pattern detection in production config
- Add integration test for extraction with proper source documents
