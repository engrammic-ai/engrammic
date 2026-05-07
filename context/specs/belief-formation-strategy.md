# Belief Formation Strategy

Discussion from 2026-05-07 architecture review session.

## The Core Question

How should beliefs form in Delta Prime? Two models:

1. **Agent-initiated**: Agent explicitly calls belief tools
2. **System-initiated**: System proposes beliefs from memory patterns

## Decision

**Analyst by default**. The system proactively synthesizes beliefs from memory corpus. Agents can accept, reject, or ignore.

Rationale: Most agents won't know to formulate beliefs. Waiting for explicit calls limits adoption to sophisticated agent builders.

## Confidence Wiring

**Decision: Two-phase calibration (Option B)**

| Phase | Formula | Stored Field |
|-------|---------|--------------|
| Write time | `source_tier * method_weight * raw_confidence` | `partial_confidence` |
| Promotion time | `partial_confidence * corroboration_factor` | `final_confidence` |

Why: Agents querying unpromoted Claims see honest (partially calibrated) confidence, not inflated raw values.

## T3/T7 Backfill

**Decision: Infer from provenance edges (Option C)**

```cypher
SET c.kind = CASE 
  WHEN EXISTS { (c)-[:SYNTHESIZED_FROM]->() } THEN "pattern"
  WHEN EXISTS { (c)-[:DECLARED_BY]->(:Agent) } THEN "rule"
  ELSE "unknown"
END
```

Expected: ~70% rule, ~20% pattern, ~10% unknown. Safe fallback.

## System-Initiated Belief Flow

```
Agent writes memories (low friction)
        |
        v
belief_synthesis_sensor (Dagster)
        |
        v
Clustering finds patterns across memories
        |
        v
System creates :ProposedBelief node
  - content: inferred belief
  - confidence: computed from evidence
  - evidence_ids: source memories
  - status: "proposed"
        |
        v
On next context_recall, surface in response:
  "proposed_beliefs": [{...}]
        |
        v
Agent calls:
  - context_accept_belief(belief_id) -> promotes to WorkingBelief
  - context_reject_belief(belief_id) -> marks rejected, won't re-propose
  - (ignore) -> stays proposed, may re-surface with more evidence
```

## New Node Type: ProposedBelief

```cypher
(:ProposedBelief {
  id: uuid,
  silo_id: string,
  content: string,
  confidence: float,
  status: "proposed" | "accepted" | "rejected",
  created_at: datetime,
  evidence_count: int
})

// Edges
(pb:ProposedBelief)-[:INFERRED_FROM]->(m:Memory)  // multiple
(pb:ProposedBelief)-[:ACCEPTED_AS]->(wb:WorkingBelief)  // on accept
```

## New Tools

```python
context_accept_belief(belief_id, session_id?, silo_id?)
  -> converts ProposedBelief to WorkingBelief, links to session

context_reject_belief(belief_id, reason?, silo_id?)
  -> marks rejected, stores reason for learning
```

## Open Questions

1. How aggressive should synthesis be? (threshold for proposing)
2. Should rejected beliefs inform future synthesis? (negative signal)
3. Rate limiting on proposals per session? (avoid spamming agent)

## Implications for Tool Surface

After this change, belief lifecycle becomes:

```
Memories (agent writes)
    |
    v [system proposes]
ProposedBelief
    |
    v [agent accepts]
WorkingBelief (session-scoped)
    |
    v [agent crystallizes]
Commitment (durable)
```

The agent's cognitive load drops: just write memories, review proposals, crystallize winners.
