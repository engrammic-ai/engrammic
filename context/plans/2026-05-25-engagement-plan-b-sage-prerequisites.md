# Engagement Plan B: SAGE Prerequisites

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Stand up sage.validator and marker infrastructure so Plan C can surface engagement payloads in recall responses.

**Depends on:** Plan A (verb promotion) — shipped 2026-05-25

**Architecture decision:** Hybrid inline-flag + batch-confirm (Approach C from brainstorm). Inline embedding check sets `contradiction_candidate` flag during writes (~20ms). Validator batch job (every 5 min) confirms via LLM, writes marker nodes, updates index.

**Tech Stack:** FastMCP, Dagster, Memgraph, Redis, structlog, primitives schema

**Spec:** `context/brainstorm/2026-05-25-engagement-surface-layers.md`

---

## Scope

### In scope for Plan B:
- Contradiction and StaleCommitment marker node types (context-service local, not primitives)
- Inline contradiction candidate flagging during `learn`/`believe` writes
- sage.validator Dagster asset (batch confirmation + marker writes)
- Marker index in Redis for fast lookup by about-set
- Synthesizer threshold tuning (refine ProposedBelief vs auto-synthesis boundaries)

### Out of scope (Plan C):
- recall response `engagement` field
- `dismiss(marker_id, reason)` verb
- `revise` extension to accept marker_id
- Soft/hard engagement detection logic

---

## Architecture

### Marker Types

Bare string labels (like `Cluster`), not primitives enum. SAGE-internal, not agent-facing.

```
:Contradiction {
  id: uuid,
  silo_id: str,
  status: "pending" | "resolved" | "dismissed",
  node_a_id: str,           # first conflicting node
  node_b_id: str,           # second conflicting node
  about_ids: list[str],     # nodes this contradiction touches (for index)
  detected_at: datetime,
  resolved_at: datetime?,
  resolution: str?,         # how it was resolved
  confidence: float,        # LLM confidence in contradiction
  expires_at: datetime,     # TTL for cleanup
}

:StaleCommitment {
  id: uuid,
  silo_id: str,
  status: "pending" | "resolved" | "dismissed",
  commitment_id: str,       # the stale Commitment node
  evidence_ids: list[str],  # new evidence that undermines it
  about_ids: list[str],
  detected_at: datetime,
  resolved_at: datetime?,
  resolution: str?,
  expires_at: datetime,
}
```

### Inline Flagging (Write Path)

During `learn` and `believe` tool calls:

1. After writing the new node, run embedding similarity check against existing Claims/Beliefs in same silo
2. If cosine similarity > `contradiction_candidate_threshold` (default 0.85):
   - Set `contradiction_candidate: true` on the new node
   - Set `contradiction_candidate_with: [node_id, ...]` for top candidates
   - Set `contradiction_candidate_at: datetime`
3. Return immediately (no LLM call in hot path)

Latency budget: <20ms (embedding cache is warm from write)

### Validator Batch Job

`sage_validator_schedule` runs every 5 minutes:

```
1. Query nodes with contradiction_candidate = true AND contradiction_candidate_at > (now - 1h)
2. For each candidate pair:
   a. LLM prompt: "Do these two claims contradict each other?"
   b. If yes with confidence > 0.7:
      - Create :Contradiction marker
      - Update Redis index
   c. Clear contradiction_candidate flag regardless
3. Query Commitments with new SUPPORTED_BY edges since last run
4. For each commitment with conflicting evidence:
   a. LLM prompt: "Does this new evidence undermine the commitment?"
   b. If yes: Create :StaleCommitment marker
5. Cleanup expired markers (expires_at < now)
```

### Redis Marker Index

Fast lookup for engagement surfacing (Plan C will query this).

```
Key: markers:{silo_id}:about:{node_id}
Value: Sorted set of marker_ids, scored by detected_at timestamp

Operations:
- ZADD on marker creation
- ZREM on marker resolution/dismissal
- ZRANGEBYSCORE for recall about-set lookup
```

TTL: Markers expire after 7 days if unresolved. Index entries cleaned up by validator.

### Synthesizer Tuning

Current thresholds in `settings.py`:
- `validator_auto_synthesis_threshold: 0.85` — above this, auto-create Belief
- `validator_proposal_threshold: 0.6` — above this (below auto), create ProposedBelief

Tuning:
- Lower `proposal_threshold` to 0.5 to surface more ProposedBeliefs for agent review
- Add `proposal_cooldown_hours: 24` — don't re-propose rejected beliefs within window
- Add `max_proposals_per_silo: 10` — cap pending ProposedBeliefs to avoid noise

---

## File Structure

```
src/context_service/
  config/
    settings.py                              # MODIFY - add validator/marker settings
  db/
    indexes.py                               # MODIFY - add Contradiction/StaleCommitment indexes
    queries.py                               # MODIFY - add marker CRUD queries
  engine/
    contradiction.py                         # CREATE - inline flagging logic
    markers.py                               # CREATE - marker write/read helpers
  mcp/
    tools/
      learn.py                               # MODIFY - add inline contradiction check
      believe.py                             # MODIFY - add inline contradiction check
  pipelines/
    assets/
      validator_contradiction.py             # CREATE - contradiction confirmation asset
      validator_stale_commitment.py          # CREATE - stale commitment detection asset
      marker_cleanup.py                      # CREATE - expired marker cleanup
    jobs/
      validator_job.py                       # CREATE - sage.validator job definition
    sensors/
      validator_sensor.py                    # CREATE - trigger on flagged candidates

tests/
  engine/
    test_contradiction.py                    # CREATE - inline flagging tests
    test_markers.py                          # CREATE - marker CRUD tests
  pipelines/
    assets/
      test_validator_contradiction.py        # CREATE - validator asset tests
```

---

## Task 0: Verify Baseline

- [ ] Run `just check` and `just test` to establish baseline
- [ ] Confirm Plan A changes are on current branch

---

## Task 1: Add Marker Node Types and Indexes

**Files:** `db/indexes.py`, `db/queries.py`

**Goal:** Define Contradiction and StaleCommitment node types with proper indexes.

- [ ] Add index queries for :Contradiction and :StaleCommitment
- [ ] Add CRUD queries for markers (create, read by silo, read by about_id, update status)
- [ ] Test: verify indexes apply cleanly to Memgraph

---

## Task 2: Create Marker Helpers

**Files:** `engine/markers.py`

**Goal:** Thin wrapper around marker queries with Redis index sync.

- [ ] `create_contradiction(silo_id, node_a_id, node_b_id, about_ids, confidence)` — writes node + updates Redis
- [ ] `create_stale_commitment(silo_id, commitment_id, evidence_ids, about_ids)` — writes node + updates Redis
- [ ] `resolve_marker(marker_id, resolution)` — updates status, clears from Redis
- [ ] `dismiss_marker(marker_id, reason)` — updates status, clears from Redis
- [ ] `get_markers_for_about_set(silo_id, about_ids)` — Redis lookup
- [ ] Tests for each function

---

## Task 3: Inline Contradiction Flagging

**Files:** `engine/contradiction.py`, `mcp/tools/learn.py`, `mcp/tools/believe.py`

**Goal:** Fast inline check during writes that flags candidates for batch confirmation.

- [ ] `check_contradiction_candidates(store, silo_id, node_id, embedding)` — returns list of candidate node_ids
- [ ] `flag_contradiction_candidate(store, node_id, candidate_ids)` — sets flags on node
- [ ] Wire into `learn` tool after node write
- [ ] Wire into `believe` tool after node write
- [ ] Config: `contradiction_candidate_threshold` (default 0.85), `contradiction_candidate_ttl_hours` (default 1)
- [ ] Tests: verify flagging works, verify no latency regression (mock embedding)

---

## Task 4: Validator Contradiction Asset

**Files:** `pipelines/assets/validator_contradiction.py`

**Goal:** Batch job that confirms flagged candidates via LLM and writes markers.

- [ ] Query flagged candidates within TTL window
- [ ] LLM confirmation prompt (structured output: {contradicts: bool, confidence: float, explanation: str})
- [ ] Create Contradiction marker on confirmation
- [ ] Clear flags regardless of outcome
- [ ] Emit metrics: candidates_processed, contradictions_confirmed, false_positives
- [ ] Tests with mocked LLM

---

## Task 5: Validator Stale Commitment Asset

**Files:** `pipelines/assets/validator_stale_commitment.py`

**Goal:** Detect commitments undermined by new evidence.

- [ ] Query Commitments with SUPPORTED_BY edges added since last run (use cursor/watermark)
- [ ] For each: check if new evidence conflicts with commitment claim
- [ ] LLM confirmation if conflict detected
- [ ] Create StaleCommitment marker
- [ ] Tests with mocked LLM

---

## Task 6: Marker Cleanup Asset

**Files:** `pipelines/assets/marker_cleanup.py`

**Goal:** Expire old unresolved markers.

- [ ] Query markers with expires_at < now
- [ ] Delete expired markers
- [ ] Remove from Redis index
- [ ] Emit metric: markers_expired

---

## Task 7: Validator Job and Schedule

**Files:** `pipelines/jobs/validator_job.py`, `pipelines/schedules.py`

**Goal:** Wire assets into Dagster job on 5-minute schedule.

- [ ] Create `sage_validator_job` combining contradiction, stale_commitment, cleanup assets
- [ ] Add `sage_validator_schedule` (*/5 * * * *)
- [ ] Register in `definitions.py`
- [ ] Test: job runs without error on empty silo

---

## Task 8: Synthesizer Threshold Tuning

**Files:** `config/settings.py`, `pipelines/assets/proposal_detection.py`

**Goal:** Refine when ProposedBeliefs are created.

- [ ] Lower `validator_proposal_threshold` from 0.6 to 0.5
- [ ] Add `proposal_cooldown_hours: 24` config
- [ ] Add `max_proposals_per_silo: 10` config
- [ ] Update `proposal_detection` to respect cooldown and cap
- [ ] Tests for new constraints

---

## Task 9: Full Sweep

- [ ] `just check` — lint + typecheck clean
- [ ] `just test` — all tests pass
- [ ] Update `context/architecture/sage-system.md` — mark validator as implemented
- [ ] Commit with summary of Plan B changes

---

## Done Criteria

Plan B is complete when:

- [ ] Contradiction and StaleCommitment node types exist with indexes
- [ ] Inline contradiction flagging wired into learn/believe (<20ms overhead)
- [ ] sage.validator job runs every 5 min, confirms candidates, writes markers
- [ ] Redis marker index populated and queryable by about-set
- [ ] Synthesizer thresholds tuned with cooldown and cap
- [ ] `just check` and `just test` green
- [ ] Architecture doc updated

---

## What Ships After Plan B

- **Plan C:** Engagement detection + soft surfacing on recall. `engagement` field in recall response, `dismiss` verb, `revise` extension.
- **Plan D:** Hard checkpoint + soft-to-hard escalation.
- **Plan E:** Skills + installer config.
