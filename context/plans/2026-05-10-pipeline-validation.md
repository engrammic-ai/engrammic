# Pipeline Validation Q/A Plan

Date: 2026-05-10
Status: Draft

## Overview

Systematic validation of Dagster pipeline assets beyond the Custodian flow (which was validated earlier today).

---

## 1. Heat Pipelines (Signals Layer)

**Assets:** `heat`, `edge_heat`
**Priority:** High (signals affect retrieval scoring)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Redis stream exists | `redis-cli XLEN silo:{id}:access_events` | Stream present |
| Events being emitted | Make recall calls, check stream grows | Events land |
| Heat asset runs | `dg asset materialize heat` | No errors, scores computed |
| Edge heat runs | `dg asset materialize edge_heat` | No errors |
| Semaphore working | High-volume recall, check no Redis connection errors | No "Too many connections" |
| Heat scores applied | Query node, check `heat` property | Score > 0 for accessed nodes |

**Risks:** Redis connection exhaustion (fixed in access_events.py, verify edge_heat has same fix)

---

## 2. Compaction/Retention (Memory Decay)

**Assets:** `compaction`, `retention`
**Priority:** High (production memory management)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Decay class honored | Query nodes with `decay_class=ephemeral` older than 7d | Should be tombstoned |
| Retention by layer | Check Memory vs Knowledge retention differs | Memory decays, Knowledge persists |
| Tombstone edges | Deleted nodes have TOMBSTONED edges | Provenance preserved |
| No data loss | Permanent nodes untouched | `decay_class=permanent` persists |

**Test data needed:** Create nodes with old `created_at` timestamps to trigger decay.

---

## 3. Extraction Pipeline

**Assets:** `extraction`, `custodian_visit`
**Priority:** Medium (document ingestion path)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Document ingestion | Store a Document node via MCP | Node created with URI |
| Claim extraction | Run extraction asset on document | Claims created |
| EXTRACTED_FROM edges | Check edges from Claim → Document | Edges exist |
| LLM invocation | Check logs for extraction model calls | Model invoked, tokens logged |
| Error handling | Ingest malformed document | Graceful failure, no crash |

---

## 4. Pattern Detection

**Assets:** `pattern_detection`, `llm_pattern_detection`
**Priority:** Medium (synthesis quality)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Statistical patterns | Run on clustered facts (need 10+ facts in cluster) | Pattern nodes created |
| LLM patterns | Run llm_pattern_detection | Richer pattern descriptions |
| Pattern → Facts linked | Check SYNTHESIZED_FROM edges | Edges exist |
| Duplicate detection | Run twice on same data | No duplicate patterns |

---

## 5. Belief Lifecycle

**Assets:** `proposal_detection`, `proposal_cleanup`, `belief_merge`, `cascade_review`
**Priority:** Medium (governance flow)

| Check | Method | Pass criteria |
|-------|--------|---------------|
| Low-confidence → ProposedBelief | Synthesize belief with confidence < 0.6 | ProposedBelief created, not Belief |
| Accept flow | `context_accept_belief` on proposal | Converts to Belief |
| Reject flow | `context_reject_belief` on proposal | Tombstoned with reason |
| Belief merge | Create near-duplicate beliefs | Merged into single belief |
| Cascade review | Supersede a fact that backs a belief | Belief flagged for review |
| Cleanup | Old rejected proposals | Garbage collected |

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
