# Plan: Metacognition and Intelligence Layer Implementation

**Status:** Complete (all phases)
**Created:** 2026-06-24
**Context:** Schema consolidation complete (v2 is now canonical). Metacognition clarified as cross-cutting capability, not a layer. Intelligence layer exists in schema but has no implementation.

## Background

From design discussion:
- Metacognition is not a fifth layer - it's a capability over the four layers
- Reflections are Memory nodes with `memory_type="reflection"` + ABOUT edges
- Intelligence layer is passive observation (system-created, not agent-written)
- Provenance is already captured via edges (DERIVED_FROM, SYNTHESIZED_FROM, SUPERSEDES)

## Phase 1: Reflection Support in MCP Tools [COMPLETE]

**Goal:** Agents can create reflections via `remember()` with proper typing and linking.

### Tasks

1. [x] **Add `memory_type` parameter to `remember()` tool**
   - `src/context_service/mcp/tools/remember.py` + `context_store.py`
   - Passed through to `store_memory()` in transactions.py

2. [x] **Add `about` parameter to `remember()` tool**
   - Creates ABOUT edges via `store_memory()` in transactions.py
   - Validation in `_validate_about_refs()`

2b. [x] **Exempt reflections from decay**
   - `retention/queries.py`: `FIND_TOMBSTONE_CANDIDATES` excludes `memory_type='reflection'`
   - Test added: `test_tombstone_candidates_excludes_reflections`

3. [x] **ABOUT edge creation path verified**
   - `sage/transactions.py:store_memory()` creates ABOUT edges when `about` param provided

4. [x] **Deprecate `layer="meta"` code path**
   - `_context_reflect()` emits DeprecationWarning + structlog warning
   - Internally routes to `store_memory(memory_type="reflection")`

5. [x] **Update `mcp_tools.yaml`**
   - `remember` description documents `memory_type` and `about` params with example

### Validation

- `remember("I was wrong about X", memory_type="reflection", about=["node_123"])` creates Memory node with ABOUT edge
- `recall(node_ids=["node_123"], include_reflections=true)` returns the reflection
- Reflection nodes appear in `trace(direction="down")` from target node

---

## Phase 2a: Session Tracking + Stuck Detection [COMPLETE]

**Goal:** Track agent sessions and detect stuck patterns.

### Tasks

1. [x] **Session tracking infrastructure**
   - Extended `session_state.py` with `QueryRecord` and query tracking
   - `record_query()` and `record_write()` methods added
   - Redis key format: `session:{silo_id}:{session_id}` (4h TTL)

2. [x] **Stuck pattern detection**
   - Created `engine/intelligence.py`
   - `detect_stuck_pattern()`: 3+ similar queries (0.7 similarity) in 5 min with no writes
   - `create_stuck_indicator()`: EpistemicState node with 4h expiry
   - Hooked into recall flow (fire-and-forget)

3. [x] **Write tracking + resolution**
   - `remember()` and `learn()` call `_track_write_and_resolve_stuck()`
   - Marks session write and resolves any active StuckIndicator

4. [x] **Intelligence labels already in primitives**
   - `IntelligenceLabel.EPISTEMIC_STATE` and `BREAKTHROUGH` exist
   - No model changes needed (EpistemicState is the StuckIndicator)

### Validation

- Agent queries same topic 3x without writing -> StuckIndicator created
- StuckIndicator visible in session context
- StuckIndicator expires with session (4h) or resolves on write

---

## Phase 2b: Breakthrough Detection + Hints [COMPLETE]

**Goal:** Detect resolutions and surface them as hints.

### Tasks

1. [x] **Breakthrough detection**
   - `resolve_stuck_indicator()` now creates Breakthrough node
   - Breakthrough stores query_pattern, action, node_id
   - Links to StuckIndicator via RESOLVED edge
   - Persists cross-session (no expiry)

2. [x] **Surface in recall**
   - `find_breakthrough_hints()` matches query against past breakthroughs
   - `recall()` adds `epistemic_hints` field when agent is stuck
   - Similarity threshold: 0.6 (more permissive than stuck detection)
   - Returns top 5 matching breakthroughs

### Validation

- Agent stuck on X -> writes solution -> Breakthrough created
- Future agent stuck on similar X -> recall includes Breakthrough hint

---

## Phase 3: Metacognitive Queries [COMPLETE]

**Goal:** Rich querying of epistemic state across the graph.

### Tasks

1. [x] **Volatility detection**
   - `detect_volatile_topics()` finds high-supersession chains
   - Exposed via `introspect(query_type="volatility")`

2. [x] **Gap detection**
   - `record_knowledge_gap()` tracks unanswered queries as KnownUnknown nodes
   - `find_knowledge_gaps()` surfaces frequent gaps
   - Hooked into recall (fire-and-forget on empty results)
   - Exposed via `introspect(query_type="gaps")`

3. [x] **Cross-agent provenance**
   - `get_belief_provenance()` traces contributing agents per belief
   - `get_agent_contribution_stats()` shows agent's impact
   - Exposed via `introspect(query_type="provenance|contributions")`

4. [x] **New MCP tool: `introspect`**
   - `mcp/tools/introspect.py` - unified interface for metacognitive queries
   - Registered in tool registry, documented in mcp_tools.yaml

---

## Dependencies

- Phase 1 is independent, ship first
- Phase 2a requires session tracking (Redis)
- Phase 2b requires Phase 2a + primitives schema additions
- Phase 3 is backlog

## Estimated Effort

| Phase | Effort | Priority |
|-------|--------|----------|
| Phase 1 | 1-2 days | High (enables agent reflection) |
| Phase 2a | 2 days | Medium (session tracking + stuck detection) |
| Phase 2b | 2 days | Medium (breakthrough + hints) |
| Phase 3 | Backlog | Low (trace() covers most cases) |

## Decisions (from review)

1. **Reflection decay:** No decay. Spec (04-metacognition.md:183-184) explicitly says "Unlike transient Memory content, reflection nodes provide permanent audit trails." Exempt `memory_type="reflection"` from decay in retention logic.

2. **Intelligence scope:** EpistemicState is session-scoped (ephemeral). Breakthrough persists cross-session (the extracted learning is valuable). Different decay classes.

3. **Detection thresholds:** Start with hardcoded defaults (3 similar queries, 5 min window). Make configurable later when we have usage data.

## Risks

1. **ABOUT edge creation path** - Verify `src/context_service/engine/` supports creating ABOUT edges during `remember()`. May need plumbing.

2. **Session boundary definition** - "timeout or explicit end" needs concrete spec. Suggest: 30 min inactivity timeout, or explicit `end_session` call.

3. **Intelligence nodes not in schema** - EpistemicState and Breakthrough exist in `IntelligenceLabel` but need full node models in primitives. Add before Phase 2.
