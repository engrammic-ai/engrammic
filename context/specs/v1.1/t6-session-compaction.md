# T6: Session Compaction (ReasoningChain → Memory)

**Status:** Draft
**Priority:** P0
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)

## Summary

Transition T6 compacts completed reasoning chains into Memory-layer traces. This preserves the "experience" of reasoning for future retrieval while allowing Intelligence-layer nodes to be ephemeral.

From spec (`03-transitions.md`):
> Intelligence -> Memory (trace): reasoning chain completes -> compact trace stored as experience

## The Problem

Currently, `:ReasoningChain` nodes created by `context_reason` persist indefinitely. The spec says Intelligence is "ephemeral inference, session-scoped" but we have no session boundary in the stateless MCP model.

Options:
1. **Time-based:** Compact chains older than T (e.g., 24h)
2. **Explicit close:** Agent calls `context_close_session(session_id)` to trigger compaction
3. **Chain completion:** Compact when chain is marked `committed: true`
4. **Hybrid:** Auto-compact on age, allow explicit close

## Proposed Design

**Hybrid approach:**
- Chains with `committed: true` are compacted immediately (they produced a Commitment)
- Chains older than 24h are batch-compacted by Dagster job
- Optional `context_close_reasoning(chain_id)` MCP tool for explicit compaction

## Compaction Output

The compacted trace is stored as a Memory-layer `:Event` node:

```cypher
(:Event {
  id: string,
  event_type: "reasoning_trace",
  content: string,           // summarized reasoning steps
  silo_id: string,
  agent_id: string,
  created_at: datetime,
  source_chain_id: string,   // original ReasoningChain id
  step_count: int,
  outcome: string            // "committed" | "abandoned" | "expired"
})-[:DERIVED_FROM]->(:ReasoningChain)  // kept briefly for audit
```

After compaction:
- The `:Event` trace is queryable via Memory-layer retrieval
- The original `:ReasoningChain` is either tombstoned or hard-deleted (configurable)

## Summarization

The `content` field is a condensed version of the chain's steps:
- If chain has <= 5 steps: inline all step conclusions
- If chain has > 5 steps: truncation (first 2 + last 2 steps with elided count)

Note: LLM summarization was considered but deferred to avoid latency/cost. The truncation approach preserves key reasoning milestones while keeping compaction fast and deterministic.

## Provenance Edge

From spec:
> `(:ReasoningChain)-[:DERIVED_FROM_EVIDENCE]->(:Document|:Passage|:Claim)+`

The compacted `:Event` inherits these edges:
```cypher
(:Event)-[:DERIVED_FROM]->(:Document|:Passage|:Claim)
```

## MCP Surface

**New tool (optional):**
```
context_close_reasoning(chain_id: str) -> {compacted: bool, event_id: str}
```

Explicitly compacts a reasoning chain. Returns the resulting Event id.

**Existing behavior:**
- `context_reason` continues to create/extend chains
- `context_commit` marks chain as committed (triggers immediate compaction)

## Dagster Integration

New asset: `reasoning_compaction`
- Schedule: hourly
- Query: chains where `committed = false AND created_at < now() - 24h`
- Action: summarize + create Event + tombstone chain

## Open Questions

1. **Tombstone vs hard-delete:** Keep chains for audit (tombstone) or delete immediately?
2. **Session concept:** Should we introduce explicit session IDs for MCP callers?
3. **Cross-chain linking:** If multiple chains reference each other, compact together or separately?
4. **Abandoned vs expired:** Different handling for chains that were explicitly abandoned vs aged out?

## Out of Scope

- T5 (Intelligence → Knowledge consensus) — already implemented
- T7 (Intelligence → Wisdom commit) — already implemented
- Reasoning chain UI/visualization — separate concern

## Done Criteria

- [ ] `:Event` node type with `event_type: "reasoning_trace"`
- [ ] Compaction logic: summarize steps, create Event, tombstone chain
- [ ] Dagster asset with hourly schedule for expired chains
- [ ] `context_commit` triggers immediate compaction
- [ ] Optional `context_close_reasoning` tool
- [ ] Integration test: reason → commit → verify Event created

## References

- Transitions spec: `../primitives/context/specs/03-transitions.md` (T6)
- Layers spec: `../primitives/context/specs/02-layers.md` (Intelligence, Memory)
- Current reasoning impl: `src/context_service/mcp/tools/context_reason.py`
