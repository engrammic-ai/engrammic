# Plan: Proposal Worker Implementation

## Goal

Implement Custodian subworker that creates ProposedBelief nodes for weak synthesis candidates.

## Spec

See `context/specs/proposal-worker.md`

## Dependencies

- Task 2 before Task 4 (queries needed)
- Tasks 3+4 before Task 5 (worker logic before Dagster asset)

## Tasks

### Task 1: Add threshold configs

**Files:**
- `src/context_service/models/silo.py`
- `src/context_service/config/settings.py`

**Changes:**
1. Add to `ValidatorOverrides`:
   ```python
   auto_synthesis_threshold: float | None = Field(default=None)
   proposal_threshold: float | None = Field(default=None)
   ```

2. Add to `settings.py` defaults:
   ```python
   validator_auto_synthesis_threshold: float = 0.7
   validator_proposal_threshold: float = 0.5
   ```

---

### Task 2: Update ProposedBelief queries

**Files:**
- `src/context_service/db/queries.py`

**Changes:**
1. Update CREATE_PROPOSED_BELIEF to add `expires_at` field (created_at + 7 days)
2. Add query: `GET_PENDING_PROPOSAL_COUNT_FOR_SILO`
3. Add query: `DELETE_EXPIRED_PROPOSALS`
4. Add query: `LIST_DENSE_CLUSTERS_WITHOUT_BELIEF_OR_PROPOSAL` - copy from `belief_synthesis.py` sensor query, add:
   ```cypher
   AND NOT EXISTS((c)<-[:SYNTHESIZED_FROM]-(:ProposedBelief {silo_id: $silo_id, status: 'pending'}))
   ```

**Note:** Existing ProposedBelief nodes will have null `expires_at` - handle gracefully.

---

### Task 3: Implement confidence estimation

**Files:**
- `src/context_service/custodian/proposal_worker.py` (new)

**Changes:**
1. Create `estimate_cluster_confidence(fact_ids)`:
   - Fetch fact confidences from cluster
   - Use `noisy_or_aggregate()` from `primitives.eag.epistemology.confidence`
   - Return float 0.0-1.0

**Reuse:** Import from `primitives.eag.epistemology.confidence` rather than custom implementation.

---

### Task 4: Implement proposal detection logic

**Files:**
- `src/context_service/custodian/proposal_worker.py`

**Changes:**
1. `get_proposal_candidates(silo_id, thresholds)`:
   - Query using `LIST_DENSE_CLUSTERS_WITHOUT_BELIEF_OR_PROPOSAL`
   - For each cluster, estimate confidence
   - Filter: `proposal_threshold <= confidence < auto_synthesis_threshold`
   
2. `create_proposal(cluster, confidence, silo_id)`:
   - Check per-silo limit via `GET_PENDING_PROPOSAL_COUNT_FOR_SILO` (max 20)
   - Generate content via LLM (see content generation note below)
   - Compute `expires_at = now + 7 days`
   - Call `CREATE_PROPOSED_BELIEF`

**Content generation:** Use structured prompt similar to `silo_synthesis.py` but for belief synthesis:
```
Given these facts: {fact_contents}
Synthesize a belief statement that captures the pattern.
```

---

### Task 5: Add Dagster asset

**Files:**
- `src/context_service/pipelines/assets/proposal_detection.py` (new)
- `src/context_service/pipelines/__init__.py`

**Changes:**
1. Create `proposal_detection` asset:
   - Deps: clustering asset
   - Iterates silos, calls proposal_worker logic
2. Schedule: cron every 10 minutes initially
3. Register in pipeline __init__

---

### Task 6: Add include_proposals to context_recall

**Files:**
- `src/context_service/mcp/tools/context_recall.py`
- `src/context_service/db/queries.py`

**Changes:**
1. Add `include_proposals: bool = False` param to context_recall
2. Add query: `GET_PENDING_PROPOSALS_FOR_SILO`
3. When `include_proposals=True`, fetch and append to results

---

### Task 7: Add expiry cleanup job

**Files:**
- `src/context_service/pipelines/assets/proposal_cleanup.py` (new)

**Changes:**
1. Daily scheduled asset
2. Calls `DELETE_EXPIRED_PROPOSALS` for each silo

---

## Verification

```bash
just check
just test
# Manual: create facts, wait for proposal detection, verify ProposedBelief created
```

## Out of Scope

- Event-driven scheduling (start with cron)
- Proposal quality ML model (start with heuristic)
- Backfill expires_at for existing ProposedBelief nodes
