# Phase: Cognitive Runtime Pivot (v2)

## Goal

Transform Engrammic from an epistemically-aware document store into a cognitive runtime that manages live belief state during agent reasoning.

## Key Conceptual Split

**Working Beliefs** (new concept, intelligence layer):
- Session-scoped, mutable, ephemeral
- Live at intelligence layer, attached to ReasoningChains via PART_OF_SESSION
- What the agent currently thinks during this reasoning session
- Can be updated in-place (no supersession chain needed)
- Discarded or promoted to Commitment at session end

**Commitments** (existing, wisdom layer):
- Durable stances the agent has crystallized
- Supersession-tracked (append-only, SUPERSEDES edges)
- Validated by Custodian over time
- Created by explicit "crystallize" action from working beliefs

## Success Criteria

- [ ] `context_recall` supports `include_content: bool = True` flag (defaults to summaries + node_ids)
- [ ] `context_belief_state(session_id)` returns active WorkingBelief nodes, confidence, contradiction flags
- [ ] `context_update_belief(belief_id, confidence, reason, content?)` mutates WorkingBelief in-place
- [ ] Sync contradiction detection on WorkingBelief writes (< 30ms)
- [ ] `context_crystallize(belief_ids)` promotes WorkingBelief -> Commitment with supersession tracking
- [ ] All changes shipped as one coherent release

---

## Data Model: WorkingBelief Node

New node type at intelligence layer:

```cypher
(:WorkingBelief {
  id: string,           // uuid
  silo_id: string,
  session_id: string,   // denormalized for fast queries
  content: string,
  confidence: float,    // 0.0 - 1.0
  created_at: datetime,
  updated_at: datetime
})
```

Edges:
- `(wb:WorkingBelief)-[:PART_OF_SESSION]->(s:ReasoningSession)`
- `(wb:WorkingBelief)-[:ABOUT]->(n)` — any node type, not just Entity

---

## Tasks

### Task 1: Add `include_content` flag to `context_recall`

**Files**:
- `src/context_service/mcp/tools/context_recall.py`

**Changes**:
1. Add `include_content: bool = True` parameter
2. When `include_content=False`:
   - Return `{node_id, layer, summary, created_at, confidence}` per node
   - `summary` = first 200 chars of content or existing summary field
3. When `include_content=True` (default, backward compatible):
   - Return full node payload (current behavior)
4. Update docstring to document the flag

**Tests**:
- `tests/integration/test_context_recall_content.py`: verify flag behavior
- Test that node_ids are always returned regardless of flag

**Done when**: Flag controls content inclusion; default preserves backward compatibility

---

### Task 2: Add WorkingBelief node type and queries

**Files**:
- `src/context_service/db/queries.py` (add queries)
- `src/context_service/db/indexes.py` (add indexes)
- `primitives/` — add WorkingBelief to schema if needed

**Changes**:
1. New indexes:
   ```cypher
   CREATE INDEX ON :WorkingBelief(silo_id);
   CREATE INDEX ON :WorkingBelief(session_id);
   ```

2. New queries:
   ```cypher
   // CREATE_WORKING_BELIEF
   CREATE (wb:WorkingBelief {
     id: $id,
     silo_id: $silo_id,
     session_id: $session_id,
     content: $content,
     confidence: $confidence,
     created_at: $created_at,
     updated_at: $created_at
   })
   WITH wb
   MATCH (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
   CREATE (wb)-[:PART_OF_SESSION]->(s)
   WITH wb
   UNWIND $about_ids AS about_id
   MATCH (n {id: about_id, silo_id: $silo_id})
   CREATE (wb)-[:ABOUT]->(n)
   RETURN wb.id AS belief_id

   // GET_WORKING_BELIEFS_FOR_SESSION
   MATCH (wb:WorkingBelief {session_id: $session_id, silo_id: $silo_id})
   OPTIONAL MATCH (wb)-[:ABOUT]->(n)
   WITH wb, collect(n.id) AS about_ids
   RETURN wb.id AS belief_id,
          wb.content AS content,
          wb.confidence AS confidence,
          wb.created_at AS created_at,
          wb.updated_at AS updated_at,
          about_ids
   ORDER BY wb.created_at DESC

   // UPDATE_WORKING_BELIEF
   MATCH (wb:WorkingBelief {id: $belief_id, silo_id: $silo_id})
   SET wb.confidence = $confidence,
       wb.updated_at = $updated_at
   SET wb.content = CASE WHEN $content IS NOT NULL THEN $content ELSE wb.content END
   RETURN wb.id AS belief_id, wb.confidence AS confidence

   // DELETE_WORKING_BELIEF
   MATCH (wb:WorkingBelief {id: $belief_id, silo_id: $silo_id})
   DETACH DELETE wb
   ```

**Tests**:
- Unit test: CRUD operations on WorkingBelief nodes
- Verify indexes exist after `ensure_indexes()`

**Done when**: WorkingBelief nodes can be created, read, updated, deleted

---

### Task 3: Implement `context_belief_state` tool

**Files**:
- `src/context_service/mcp/tools/context_belief_state.py` (new)
- `src/context_service/mcp/server.py` (register)

**Changes**:
1. New query for contradiction detection:
   ```cypher
   // DETECT_CONTRADICTIONS_IN_SESSION
   MATCH (wb1:WorkingBelief {session_id: $session_id, silo_id: $silo_id})
   MATCH (wb2:WorkingBelief {session_id: $session_id, silo_id: $silo_id})
   WHERE wb1.id < wb2.id
   MATCH (wb1)-[:ABOUT]->(n)<-[:ABOUT]-(wb2)
   RETURN DISTINCT wb1.id AS belief_a, wb2.id AS belief_b
   LIMIT 10
   ```

2. Tool implementation:
   ```python
   async def context_belief_state(
       session_id: str,
       about: list[str] | None = None,
       silo_id: str | None = None,
   ) -> dict[str, Any]:
       # Returns:
       # {
       #   "working_beliefs": [{belief_id, content, confidence, created_at, updated_at, about_ids}],
       #   "potential_contradictions": [{belief_a, belief_b}],
       #   "reflection_suggested": bool,  # True if contradictions exist
       #   "session_id": str,
       # }
   ```

**Tests**:
- `tests/integration/test_belief_state.py`: create session with working beliefs, verify returned
- Test filtering by `about` node
- Test `reflection_suggested` flag when contradictions exist

**Done when**: Agents can query live belief state for a session

---

### Task 4: Wire sync contradiction detection into WorkingBelief writes

**Files**:
- `src/context_service/mcp/tools/context_store.py`
- `src/context_service/db/queries.py`

**Changes**:
1. New query (no `:Entity` label constraint):
   ```cypher
   // DETECT_CONFLICTING_WORKING_BELIEFS
   MATCH (new:WorkingBelief {id: $new_belief_id, silo_id: $silo_id})
   MATCH (new)-[:ABOUT]->(n)
   MATCH (other:WorkingBelief)-[:ABOUT]->(n)
   WHERE other.id <> $new_belief_id
     AND other.session_id = new.session_id
   RETURN DISTINCT other.id AS conflict_id
   LIMIT 10
   ```

2. After creating WorkingBelief:
   - Run detection query
   - Include `potential_conflicts: list[str]` in response if any found
   - Target < 30ms (bounded by LIMIT 10, indexed on silo_id + session_id)

**Tests**:
- `tests/integration/test_working_belief_conflict.py`: write two beliefs about same node, verify conflict_ids returned
- Benchmark: verify < 30ms on test dataset

**Done when**: WorkingBelief writes return detected conflicts in ack

---

### Task 5: Implement `context_update_belief` tool

**Files**:
- `src/context_service/mcp/tools/context_update_belief.py` (new)
- `src/context_service/mcp/server.py` (register)

**Changes**:
1. Tool implementation (in-place mutation, no supersession):
   ```python
   async def context_update_belief(
       belief_id: str,
       confidence: float,
       reason: str,
       content: str | None = None,
       silo_id: str | None = None,
   ) -> dict[str, Any]:
       # 1. Validate WorkingBelief exists
       # 2. Update in-place (confidence, optionally content)
       # 3. Append reason to audit log (optional, could be stored on node)
       # Returns: {belief_id, confidence, content, updated_at, reason}
   ```

2. Uses UPDATE_WORKING_BELIEF query from Task 2

**Tests**:
- `tests/integration/test_update_belief.py`: update belief, verify changes persisted
- Test optional content update

**Done when**: Agents can revise working beliefs in-place

---

### Task 6: Implement `context_crystallize` tool

**Files**:
- `src/context_service/mcp/tools/context_crystallize.py` (new)
- `src/context_service/mcp/server.py` (register)

**Changes**:
1. New query:
   ```cypher
   // CRYSTALLIZE_TO_COMMITMENT
   MATCH (wb:WorkingBelief {id: $belief_id, silo_id: $silo_id})
   CREATE (cm:Commitment {
     id: $commitment_id,
     silo_id: $silo_id,
     content: wb.content,
     confidence: wb.confidence,
     created_at: $created_at,
     valid_from: $valid_from,
     crystallized_from: wb.id
   })
   // Check for existing Commitment to supersede
   WITH wb, cm
   OPTIONAL MATCH (wb)-[:ABOUT]->(n)<-[:ABOUT]-(existing:Commitment)
   WHERE NOT EXISTS { (existing)<-[:SUPERSEDES]-(:Commitment) }
     AND existing.silo_id = $silo_id
   WITH wb, cm, collect(DISTINCT existing) AS to_supersede
   // Copy ABOUT edges
   WITH wb, cm, to_supersede
   MATCH (wb)-[:ABOUT]->(n)
   CREATE (cm)-[:ABOUT]->(n)
   // Create SUPERSEDES edges to prior commitments
   WITH cm, to_supersede
   UNWIND to_supersede AS old
   CREATE (cm)-[:SUPERSEDES {reason: $reason, created_at: $created_at}]->(old)
   SET old.valid_to = $valid_from
   RETURN cm.id AS commitment_id
   ```

2. Tool implementation:
   ```python
   async def context_crystallize(
       belief_ids: list[str],
       reason: str | None = None,
       silo_id: str | None = None,
   ) -> dict[str, Any]:
       # 1. For each belief_id, promote to Commitment
       # 2. Create SUPERSEDES edges to any existing Commitments about same nodes
       # 3. Optionally delete the WorkingBelief (or leave for audit)
       # Returns: {commitment_ids: list[str], superseded: list[str]}
   ```

**Tests**:
- `tests/integration/test_crystallize.py`: create working belief, crystallize, verify Commitment exists
- Test supersession: crystallize twice about same node, verify SUPERSEDES edge

**Done when**: Agents can promote ephemeral beliefs to durable commitments

---

## Implementation Order

1. Task 2 (WorkingBelief node + queries) — foundation
2. Task 1 (include_content flag) — lowest risk, no new nodes
3. Task 3 (context_belief_state) — core read path
4. Task 5 (context_update_belief) — core write path
5. Task 4 (conflict detection) — enhance write path
6. Task 6 (context_crystallize) — promotion path

Tasks 1 and 2 can run in parallel. Tasks 3-6 depend on Task 2.

---

## Tool Surface After Implementation

5 core tools (was 4):
- `context_store` — unified writes to any layer
- `context_recall` — unified reads (now with `include_content` flag)
- `context_link` — create typed relationships
- `context_admin` — silo management, provenance, history
- `context_belief_state` — query live session belief state

2 belief-specific tools:
- `context_update_belief` — mutate working belief in-place
- `context_crystallize` — promote working beliefs to commitments

Note: `context_load` folded into `context_recall` with `include_content: true`.

---

## Non-Goals (explicitly out of scope)

- Custodian changes (stays as batch path with 120s timeout)
- Extraction pipeline changes
- Backward compatibility shims
- LLM-based conflict resolution (detection only, no resolution)
- Linking wisdom-layer Commitments to sessions (they're durable, not session-scoped)

---

## Rollout

Ship as single coherent release. No feature flags needed since this is a clean cut.
