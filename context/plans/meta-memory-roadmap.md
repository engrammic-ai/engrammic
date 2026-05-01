# Meta-Memory Roadmap

> Enabling metacognition: agents reasoning about their own epistemic state.

## Overview

Meta-Memory is a cross-cutting capability that spans all four EAG layers (Memory, Knowledge, Wisdom, Intelligence). It enables agents to:

1. **Trace provenance** — "Why do I believe X?"
2. **Time-travel** — "What did I know on date Y?"
3. **Track belief history** — "How has my understanding evolved?"
4. **Reflect** — Store observations about their own cognition

This is not a 5th layer. It's infrastructure that makes the four layers introspectable.

## Why This Matters

| Without Meta-Memory | With Meta-Memory |
|---------------------|------------------|
| Agent sees current truth only | Agent can query historical state |
| "I believe X" | "I believe X because doc D said so" |
| Silent overwrites | Explicit supersession chains |
| No self-reflection | Agent can notice and record belief changes |

**Differentiator**: Most memory systems are write-once, read-current. Meta-Memory makes the full epistemic history queryable.

## Phases

### Phase 1: Provenance Queries (Low effort, High value) — COMPLETE 2026-05-01

**Goal**: Answer "Why do I believe X?"

**Scope**:
- MCP tool: `context_provenance(node_id)`
- Traverses REFERENCES, DERIVED_FROM, PROMOTED_FROM, SYNTHESIZED_FROM edges
- Returns citation chain with confidence scores

**Completed**:
- `db/queries.py:PROVENANCE_CHAIN` and `PROVENANCE_ROOT_SOURCES` now include REFERENCES
- `context_provenance` MCP tool wired in `mcp/tools/context_provenance.py`
- `context_get_reflections` MCP tool added for Phase 4 retrieval

**Spec**: [phase-1-provenance.md](./meta-memory/phase-1-provenance.md)

---

### Phase 2: Time-Travel Queries (Medium effort, High value)

**Goal**: Answer "What did I know on date Y?"

**Scope**:
- Add `as_of` parameter to `context_lookup`
- Filter by `valid_from <= as_of < valid_to`
- Return nodes that were "true" at that point in time

**Already have**:
- Bi-temporal fields on all nodes (`valid_from`, `valid_to`, `created_at`)

**Need to build**:
- Query modification to filter by temporal bounds
- MCP tool parameter extension
- Handle edge cases (null valid_to = still valid)

**Spec**: [phase-2-time-travel.md](./meta-memory/phase-2-time-travel.md)

---

### Phase 3: Belief History (Medium effort, Medium value)

**Goal**: Answer "How has my understanding of X evolved?"

**Scope**:
- New MCP tool: `context_belief_history(subject)`
- Traverse SUPERSEDES edges to build evolution timeline
- Group by subject, show confidence changes over time

**Already have**:
- SUPERSEDES edges
- Timestamps on supersession

**Need to build**:
- Aggregation query across supersession chains
- Timeline response schema
- Subject identification (how to group related facts)

**Spec**: [phase-3-belief-history.md](./meta-memory/phase-3-belief-history.md)

---

### Phase 4: Reflection (Higher effort, High value)

**Goal**: Agent can store meta-observations about its own cognition.

**Scope**:
- New node type: `:MetaObservation`
- New MCP tool: `context_reflect(observation, about: [node_ids])`
- New MCP tool: `context_get_reflections(node_id)`
- Agent can record "I noticed my belief changed" or "I was wrong about X"

**Completed 2026-05-01**:
- `context_reflect` MCP tool (stores MetaObservation + ABOUT edges)
- `context_get_reflections` MCP tool (retrieves by ABOUT edge)
- `services/context.py:reflect()` and `get_reflections()` methods

**Remaining**:
- Formalize MetaObservation in `primitives.schema.labels`
- Add ABOUT edge to `CITEEdgeType`
- Add indexes on `:MetaObservation`

**Spec**: [phase-4-reflection.md](./meta-memory/phase-4-reflection.md)

---

## Implementation Order

```
Phase 1 (Provenance) ──────────────────────────────────►
         Phase 2 (Time-Travel) ────────────────────────►
                   Phase 3 (Belief History) ───────────►
                              Phase 4 (Reflection) ────►
```

Phases can overlap. Phase 1 is prerequisite for none. Phases 2-4 are independent.

**Recommended start**: Phase 1 (provenance) — high value, low effort, immediately differentiating.

## Storage Model

### Current (sufficient for Phases 1-3)

```cypher
// Nodes have bi-temporal fields
(:Claim {valid_from, valid_to, created_at, confidence})
(:Fact {valid_from, valid_to, created_at, confidence})
(:Document {created_at, source_uri})

// Edges track relationships
(:Claim)-[:REFERENCES]->(:Document)
(:Fact)-[:SUPERSEDES]->(:Fact)
```

### Phase 4 Addition

```cypher
// New node type
(:MetaObservation {
  id,
  content,           // "I noticed my belief about X changed"
  observation_type,  // "belief_change" | "confidence_shift" | "contradiction"
  created_at,
  agent_id
})

// New edge type
(:MetaObservation)-[:ABOUT]->(:Claim|:Fact|:Document)
```

## MCP Interface Summary

| Phase | Tool | Signature |
|-------|------|-----------|
| 1 | `context_provenance` | `(node_id: str) -> ProvenanceChain` |
| 2 | `context_lookup` | `(query: str, as_of: date = None) -> list[Node]` |
| 3 | `context_belief_history` | `(subject: str) -> list[BeliefState]` |
| 4 | `context_reflect` | `(observation: str, about: list[str]) -> MetaObservation` |
| 4 | `context_get_reflections` | `(node_id: str) -> list[MetaObservation]` |

## Success Metrics

| Phase | Metric |
|-------|--------|
| 1 | Agent can answer "why do I believe X" with citation chain |
| 2 | Agent can answer "what did I know last week" accurately |
| 3 | Agent can show belief evolution timeline |
| 4 | Agent can store and retrieve meta-observations |

## Open Questions

1. **Subject identification**: How do we group related facts for belief history? By entity ID? By predicate? By embedding similarity?

2. **Reflection triggers**: Should the system auto-generate meta-observations on supersession? Or only when agent explicitly reflects?

3. **Retention**: Do meta-observations decay? Or persist indefinitely?

4. **Cross-silo**: Can an agent reflect on beliefs across silos? Or is reflection silo-scoped?
