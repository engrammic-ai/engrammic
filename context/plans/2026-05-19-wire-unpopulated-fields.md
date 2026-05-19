# Wire Unpopulated Optional Schema Fields

**Issue:** https://github.com/engrammic-ai/engrammic/issues/38
**Status:** planning
**Priority:** low (reduced scope after verification)

## Problem

Audit found 6 optional schema fields that are defined but never populated. Original audit identified 16 but verification found 10 were false positives (actually wired in causal pipeline, retrieval, and compaction code).

## Verified Dead Fields

| Field | Model | Issue |
|-------|-------|-------|
| `compacted_by_model` | `ReasoningChain` | `COMPACT_CHAIN` in `engine/queries.py` never called |
| `rationale_chain_id` | `Commitment` | Query param exists, no caller populates |
| `created_at` | `services.models.Silo` | Service layer never reads from DB |
| `references_upserted` | `WritePathResult` | Hardcoded `0` in all 3 sites |
| `properties` | `Node` (dedup path) | Returns `{}` on cache hit |
| `label` | `Node` (store path) | Not passed through |

## False Positives (removed from scope)

Verification found these ARE wired:
- All 5 BinaryEdge causal fields (in `pipelines/assets/causal.py`)
- `ReasoningChain.compacted_at` (via `db/queries.py` + `compaction.py`)
- `Node.extraction_status` (written AND read in `extraction/service.py`)
- `TierConfig.reranker/query_expander` (wired to `context_query.py`)
- `SPOClaim.qualifiers` (forwarded in `services/context.py:1015`)

## Tasks

### Task 1: Fix `services.models.Silo.created_at`

**Files:**
- `src/context_service/services/silo.py`

**Changes:**
1. In `get_or_create()` CREATE query (~line 60-69): Add `created_at: datetime()` to node properties
2. In `get_by_id()` (~line 86-93): Add `s.created_at AS created_at` to Cypher RETURN clause
3. In `get_by_id()` (~line 102): Add `created_at=_parse_datetime(row.get("created_at"))` to Silo constructor
4. In `list()` (~line 113-120): Add `s.created_at AS created_at` to Cypher RETURN clause  
5. In `list()` (~line 124): Add `created_at=_parse_datetime(row.get("created_at"))` to Silo constructor
6. Add inline `_parse_datetime` helper (copy pattern from `memgraph_store.py:65`, don't import to avoid coupling to concrete store)

**Test:** `test_silo_created_at_hydration`

### Task 2: Fix `assert_claim()` dedup to preserve properties

**Files:**
- `src/context_service/services/context.py`

**Changes:**
1. Line ~1022-1031: Add `c.properties AS properties` to Cypher RETURN clause
2. Line ~1041: Change `properties={}` to `properties=loads(row.get("properties") or "{}")`

**Note:** Verify storage format - if `properties` is stored as JSON string (common in Memgraph), handle both dict and str types.

**Test:** `test_assert_claim_dedup_preserves_properties`

### Task 3: Wire `Commitment.rationale_chain_id`

**Files:**
- `src/context_service/db/queries.py` (CRYSTALLIZE_TO_COMMITMENT query)
- `src/context_service/mcp/tools/context_crystallize.py`

**Changes:**
1. In `db/queries.py` line ~1307-1316: Add `rationale_chain_id: $rationale_chain_id` to the Commitment CREATE clause in `CRYSTALLIZE_TO_COMMITMENT`
2. In `context_crystallize.py` `_crystallize_one()`: Add `rationale_chain_id` param, pass to query params
3. In `context_crystallize.py` `_context_crystallize()`: Accept optional `chain_id` from session context, pass to `_crystallize_one()`

**Note:** This wires the crystallization path (WorkingHypothesis -> Commitment). The direct `commit_belief()` path in `services/context.py` is a separate code path used by the `believe` tool - that can be wired separately if needed.

**Test:** `test_commitment_links_to_reasoning_chain`

### Task 4: Wire `WritePathResult.references_upserted`

**Files:**
- `src/context_service/custodian/write_path.py`
- `src/context_service/custodian/silo_synthesis.py`

**Changes:**
1. Track count when creating CITES edges (batch at line ~372-376)
2. Return actual count instead of hardcoded `0` at lines 255, 425
3. Same fix in `silo_synthesis.py:102`

**Definition:** "references" = CITES edges created (canonicalized URL references)

**Test:** `test_write_path_counts_references`

### Task 5: Wire `ReasoningChain.compacted_by_model`

**Decision:** Defer or remove

The `COMPACT_CHAIN` query in `engine/queries.py:1041` sets both `compacted_at` and `compacted_by_model`, but the query is never called. The live compaction path uses `db/queries.py:658` (`TOMBSTONE_REASONING_CHAIN`) which only sets `compacted_at`.

**Options:**
1. Add `compacted_by_model` to `TOMBSTONE_REASONING_CHAIN` and pass model ID from `compaction.py`
2. Remove `compacted_by_model` from schema (not needed if we track via `compacted_at` + logs)
3. Defer until compaction redesign

**Recommendation:** Option 1 (wire it) - 30 min fix

**Implementation:**
1. Add `compacted_by_model: $compacted_by_model` to `TOMBSTONE_REASONING_CHAIN` in `db/queries.py:655`
2. In `compaction.py` `compact_reasoning_chain()` (~line 157-165): pass `compacted_by_model=model_spec.model` (available at line 123)

### Task 6: Evaluate `Node.label` in `store()`

**Decision:** No action needed

The `label` field on `Node` represents the CITE graph-schema label (`:Document`, `:Passage`, `:Claim`). In `store()`, callers pass `node_type` which serves the same purpose. The `label` field is only used as a fallback in `_node_from_record` hydration from existing graph nodes.

Adding a `label` param to `store()` would create confusion between `type` and `label`. Leave as-is.

## Effort Estimate (revised)

| Task | Est. Hours |
|------|------------|
| Task 1 (Silo.created_at) | 1h |
| Task 2 (properties dedup) | 0.5h |
| Task 3 (rationale_chain_id) | 1.5h |
| Task 4 (references_upserted) | 1h |
| Task 5 (compacted_by_model) | 0.5h |
| Task 6 (label) | 0h (no action) |
| **Total** | ~4.5h |

## Dependencies

- Tasks 1-4 are independent, can parallelize
- Task 5 depends on understanding compaction flow (already verified)
