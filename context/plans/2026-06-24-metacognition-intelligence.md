# Plan: Metacognition and Intelligence Layer Implementation

**Status:** Draft
**Created:** 2026-06-24
**Context:** Schema consolidation complete (v2 is now canonical). Metacognition clarified as cross-cutting capability, not a layer. Intelligence layer exists in schema but has no implementation.

## Background

From design discussion:
- Metacognition is not a fifth layer - it's a capability over the four layers
- Reflections are Memory nodes with `memory_type="reflection"` + ABOUT edges
- Intelligence layer is passive observation (system-created, not agent-written)
- Provenance is already captured via edges (DERIVED_FROM, SYNTHESIZED_FROM, SUPERSEDES)

## Phase 1: Reflection Support in MCP Tools

**Goal:** Agents can create reflections via `remember()` with proper typing and linking.

### Tasks

1. **Add `memory_type` parameter to `remember()` tool**
   - File: `src/context_service/mcp/tools/context_store.py`
   - Add optional `memory_type: str` param (default: None)
   - Valid values: `observation`, `reflection`, `event`, `document`
   - Store as node property

2. **Add `about` parameter to `remember()` tool**
   - When `memory_type="reflection"`, require or allow `about: list[str]`
   - Create ABOUT edges to referenced node IDs
   - Validate node IDs exist in same silo

2b. **Exempt reflections from decay**
   - In retention/decay logic, skip nodes with `memory_type="reflection"`
   - Per spec: "reflection nodes provide permanent audit trails"

3. **Verify ABOUT edge creation path**
   - Check `src/context_service/engine/` supports creating ABOUT edges
   - May need to add edge creation to `store_memory()` or similar
   - Test: `remember()` with `about` param creates edges correctly

4. **Deprecate `layer="meta"` code path**
   - Add deprecation warning to `_context_reflect()`
   - Document migration: `layer="meta"` -> `remember(memory_type="reflection")`
   - Keep working for backward compat, remove in future version

4. **Update `mcp_tools.yaml`**
   - Document `memory_type` and `about` params in `remember` description
   - Add examples for reflection usage

### Validation

- `remember("I was wrong about X", memory_type="reflection", about=["node_123"])` creates Memory node with ABOUT edge
- `recall(node_ids=["node_123"], include_reflections=true)` returns the reflection
- Reflection nodes appear in `trace(direction="down")` from target node

---

## Phase 2a: Session Tracking + Stuck Detection

**Goal:** Track agent sessions and detect stuck patterns.

### Tasks

1. **Session tracking infrastructure**
   - Track agent actions per session (tool calls, nodes created)
   - Store session state in Redis (key: `session:{silo_id}:{agent_id}:{session_id}`)
   - Session boundary: 30 min inactivity timeout or explicit end
   - File: `src/context_service/engine/sessions.py` (extend existing)

2. **Stuck pattern detection**
   - File: `src/context_service/engine/intelligence.py` (new)
   - Detect: 3+ similar queries in 5 min window with no writes
   - Create StuckIndicator node (session-scoped, ephemeral)
   - Link to query nodes via ABOUT edges

3. **Add Intelligence node models to primitives**
   - EpistemicState, Breakthrough, StuckIndicator in `primitives/schema/models.py`
   - Ensure labels match `IntelligenceLabel` enum

### Validation

- Agent queries same topic 3x without writing -> StuckIndicator created
- StuckIndicator visible in session context
- StuckIndicator expires with session

---

## Phase 2b: Breakthrough Detection + Hints

**Goal:** Detect resolutions and surface them as hints.

### Tasks

1. **Breakthrough detection**
   - Detect: StuckIndicator exists -> agent writes something -> confidence spike
   - Record resolution action (what tool call, what content)
   - Create Breakthrough node (persists cross-session)
   - Link to StuckIndicator via resolved relationship

2. **Surface in recall**
   - When agent is in stuck state, check for similar past Breakthroughs
   - Add `epistemic_hints` field to recall response
   - Similarity: same topic cluster or query embedding similarity

### Validation

- Agent stuck on X -> writes solution -> Breakthrough created
- Future agent stuck on similar X -> recall includes Breakthrough hint

---

## Phase 3: Metacognitive Queries (Backlog)

**Goal:** Rich querying of epistemic state across the graph.
**Status:** Deferred. `trace()` already covers most use cases.

### Tasks (when needed)

1. **Volatility detection** - surface warning for high-supersession topics
2. **Gap detection** - track unanswered queries as "known unknowns"
3. **Cross-agent provenance** - contribution graph per belief

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
