# Phase: Review Followup (2026-05-08)

## Context

Codebase review on 2026-05-08 identified 19 P0+P1 issues. 16 were fixed in the initial pass. This plan covers the 4 deferred items: 1 performance optimization and 3 test coverage gaps.

## Completed (main branch)

- S-001: Cypher injection validation
- L-001: R1_THRESHOLD consensus requirement
- L-002: Crystallizations route through Wisdom (T7)
- AI-001/002: Prompt injection sanitization
- AI-003/004: Synthesis agent timeouts
- P-001: Batch node fetches in context_get
- P-003: Parallelize chain compaction
- E-001/002/003: Qdrant cluster error handling
- D-001/002: Rebrand + spec update
- N-006: mypy no-any-return fix

## Remaining Tasks

### Task 1: P-002 Causal Invalidation Batching

**File**: `src/context_service/engine/causal_invalidation.py:71-99`

**Issue**: O(N*depth) database round-trips. Per-edge query + write in nested loop.

**Current**:
```python
for edge_id in frontier:
    rows = await client.execute_query(_FIND_DERIVED_EDGES, {"edge_id": edge_id})
    for row in rows:
        await client.execute_write(_TOMBSTONE_DERIVED_EDGE, {...})
```

**Fix**:
1. Rewrite `_FIND_DERIVED_EDGES` to accept `UNWIND $edge_ids`
2. Batch tombstone writes with single UNWIND query
3. Collect all derived edges per depth level, then batch-write

**Effort**: M

---

### Task 2: B-001 Protocol Interface Tests

**File**: `src/context_service/engine/protocols.py`

**Issue**: 42 direct importers, 97 transitive reach, only 2 test files.

**Fix**: Add unit tests covering:
- GraphStore protocol methods
- VectorStore protocol methods
- CacheStore protocol methods
- Error contract verification

**Target**: `tests/engine/test_protocols.py`

**Effort**: M

---

### Task 3: B-002 JSON Utility Tests

**File**: `src/context_service/utils/json.py`

**Issue**: 126 transitive reach, only 1 test file. Serialization bugs here corrupt data silently.

**Fix**: Add edge-case tests:
- datetime/UUID serialization
- nested structures
- None handling
- large payloads
- malformed input

**Target**: `tests/utils/test_json.py`

**Effort**: M

---

### Task 4: B-003 Proposal Worker Tests

**Files**: 
- `src/context_service/custodian/proposal_worker.py`
- `config/prompts/custodian/proposal_synthesis.yaml`

**Issue**: New code with only 1 test. Drives ProposedBelief synthesis.

**Fix**: Add tests for:
- `synthesize_proposal_content` with various inputs
- `get_proposal_candidates` query logic
- `create_proposal` edge cases
- Prompt injection sanitization verification

**Target**: `tests/custodian/test_proposal_worker.py`

**Effort**: M

---

## Verification

```bash
just check   # lint + typecheck
just test    # pytest
```

## Priority

1. Task 1 (P-002) - only perf fix, impacts invalidation latency
2. Tasks 2-4 (B-*) - test coverage, reduces regression risk
