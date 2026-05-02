# Auto-Reflection

**Status:** Draft
**Priority:** P2
**Roadmap:** [v1.1-roadmap.md](../../plans/v1.1-roadmap.md)
**Depends on:** T4 (Belief Revision)

## Summary

Auto-reflection generates `:MetaObservation` nodes automatically when significant epistemic events occur, without requiring an agent to call `context_reflect` explicitly.

From metacognition spec (`04-metacognition.md`), open question:
> Should the system auto-generate observations on supersession, confidence changes, or contradictions?

## Current State

- `context_reflect` creates `:MetaObservation` nodes with `ABOUT` edges
- Observations are always agent-initiated (explicit call)
- No system-generated observations exist

## Triggers for Auto-Reflection

| Event | Observation Type | Content Template |
|-------|------------------|------------------|
| Fact supersession (T2) | `belief_change` | "Fact '{old}' was superseded by '{new}' due to {reason}" |
| Belief revision (T4) | `belief_change` | "Belief about '{subject}' was revised due to evidence shift ({magnitude}%)" |
| Confidence drop | `confidence_shift` | "Confidence in '{subject}' dropped from {old} to {new}" |
| Contradiction detected | `contradiction` | "Contradiction detected between '{a}' and '{b}'" |
| High uncertainty query | `uncertainty` | "Query '{query}' returned results with avg confidence {conf}" |

## Schema

Same as manual reflection:
```cypher
(:MetaObservation {
  id: string,
  content: string,
  observation_type: string,
  confidence: float,
  created_at: datetime,
  agent_id: string,         // "system" for auto-generated
  silo_id: string,
  auto_generated: true      // new field to distinguish
})-[:ABOUT]->(:Fact|:Belief|:*)
```

New field: `auto_generated: bool` to distinguish from agent-initiated reflections.

## Implementation

### Hook Points

1. **Supersession hook:** In `custodian/supersession.py`, after `SUPERSEDES` edge is created
2. **Revision hook:** In T4 belief revision (when implemented), after new Belief created
3. **Confidence hook:** After any write that changes node confidence by > threshold
4. **Contradiction hook:** In extraction filter when contradiction is detected but not resolved

### Batching

Auto-reflections should not block the triggering operation. Options:
- **Async write:** Fire-and-forget to a queue, background worker creates observations
- **Dagster job:** Batch process events → observations periodically
- **Inline but fast:** Direct write, no LLM call (template-based content)

**Recommendation:** Template-based inline writes (no LLM). Fast, deterministic, auditable.

### Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `AUTO_REFLECT_ENABLED` | false | Feature flag |
| `AUTO_REFLECT_SUPERSESSION` | true | Generate on supersession |
| `AUTO_REFLECT_REVISION` | true | Generate on belief revision |
| `AUTO_REFLECT_CONFIDENCE_THRESHOLD` | 0.2 | Min confidence delta to trigger |
| `AUTO_REFLECT_CONTRADICTION` | true | Generate on detected contradictions |

## Agent Identity

Auto-generated observations use `agent_id: "system"` to distinguish from agent-initiated reflections.

Alternative: Use the agent that triggered the event (e.g., the agent whose assertion caused supersession). This creates attribution but may be misleading (the agent didn't "reflect", the system did).

**Recommendation:** Use `agent_id: "system"` for clarity.

## Retrieval

Auto-reflections are returned by:
- `context_get_reflections(node_id)` — includes auto-generated
- `context_query(layer="meta")` — if we add meta-layer querying

Optional filter: `exclude_auto: bool` parameter on reflection queries.

## Open Questions

1. **Volume:** Will auto-reflection create too many nodes? Need retention policy?
2. **Value:** Are auto-generated observations useful, or just noise?
3. **LLM enhancement:** Should auto-reflections be LLM-enhanced (richer content)?
4. **Cross-silo:** If supersession crosses silo boundary (shared fact), which silo gets the observation?

## Out of Scope

- Agent-initiated reflection (already implemented)
- Meta-meta-reflection (observations about observations)
- Reflection-triggered actions (e.g., alert on contradiction)

## Done Criteria

- [ ] `auto_generated` field on MetaObservation schema
- [ ] Supersession hook creates auto-reflection
- [ ] Revision hook creates auto-reflection (after T4)
- [ ] Configuration flags for each trigger type
- [ ] `agent_id: "system"` for auto-generated
- [ ] Integration test: supersede fact → verify auto MetaObservation created
- [ ] `context_get_reflections` returns auto-generated observations

## References

- Metacognition spec: `../primitives/context/specs/04-metacognition.md`
- Current reflection impl: `src/context_service/mcp/tools/context_reflect.py`
- Supersession: `src/context_service/custodian/supersession.py`
