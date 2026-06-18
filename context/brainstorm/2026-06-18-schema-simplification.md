# Schema Simplification

Date: 2026-06-18
Status: Decided (tiebreaker complete)

## Context

Pruning CITE schema from 15+ nodes and 23 edges to minimal set that supports:
1. SAGE passive synthesis (dreaming layer)
2. Fast agent writes (remember/learn only)
3. Hindsight-style temporal versioning

## Final Schema (after 3-reviewer adversarial process)

### Nodes (5)

| Label | Layer | Purpose | Agent writes? |
|-------|-------|---------|---------------|
| Memory | Memory | Raw observations via `remember` | Yes |
| Claim | Knowledge | Evidence-backed assertions via `learn` | Yes |
| Fact | Knowledge | SAGE-promoted from corroborated Claims | No (SAGE) |
| Belief | Wisdom | SAGE-synthesized from Facts | No (SAGE) |
| Commitment | Wisdom | Agent decisions via `decide` | Yes |

Note: Commitment kept as separate type (tiebreaker decision) - trust model and code paths differ from Belief.

### Edges (6)

| Edge | Purpose | Who creates |
|------|---------|-------------|
| DERIVED_FROM | Claim -> Evidence provenance | Agent/SAGE |
| SYNTHESIZED_FROM | Belief -> Fact chain | SAGE |
| SUPERSEDES | Version chain | Agent or SAGE |
| SUPPORTS | Positive epistemology (confidence propagation) | SAGE |
| CONTRADICTS | Negative epistemology (conflict detection) | SAGE |
| ABOUT | Meta-structure targeting | Agent |

### Intelligence Layer: DEFERRED

See "Intelligence Layer Considerations" section below.

## Kill List (Final)

### Nodes removed

| Node | Reason | Tiebreaker |
|------|--------|------------|
| Document, Passage, Utterance, Event, Observation | Collapse into Memory | Agreed |
| ProposedBelief | Use Belief with confidence threshold on recall | Agreed |
| Pattern | Premature abstraction | Agreed |
| ReasoningChain, QueryContext, WorkingHypothesis | Intelligence layer deferred | Agreed |
| MetaObservation | Use Memory with flag | Agreed |
| Entity, Predicate | RAG scaffolding, extract on read | Tiebreaker: KILL |
| Cluster | SAGE batch clustering deprecated | Agreed |

### Nodes KEPT (tiebreaker overruled)

| Node | Reason |
|------|--------|
| Commitment | Trust model differs from Belief, separate code paths, StaleCommitment markers |

### Edges removed

| Edge | Reason | Tiebreaker |
|------|--------|------------|
| EXTRACTED_FROM | RAG scaffolding, DERIVED_FROM covers provenance | Tiebreaker: KILL |
| REFERENCES | Covered by DERIVED_FROM + ABOUT | Agreed |
| CRYSTALLIZED_INTO, DECLARED_BY | Hypothesize/commit flow deferred | Agreed |
| MENTIONS, USES_PREDICATE | Entity extraction deferred | Agreed |
| CAUSES, PREVENTS | Causal reasoning premature | Agreed |
| COVERS, OBSERVED_IN | Pattern stuff premature | Agreed |
| TRACED_FROM, CONSENSUS_FROM | Reasoning chains deferred | Agreed |
| MEMBER_OF | SAGE batch clustering deprecated | Tiebreaker: KILL |
| CORROBORATES | Redundant with SUPPORTS | Agreed |

### Edges KEPT (tiebreaker overruled)

| Edge | Reason |
|------|--------|
| SUPPORTS | Epistemology distinct from provenance, confidence diffusion needs it |

## Review Summary

Two-reviewer adversarial process:

**Reviewer 1 (conservative):** Keep MEMBER_OF, Commitment, SUPPORTS, EXTRACTED_FROM, Entity

**Reviewer 2 (aggressive):** 
- MEMBER_OF is artifact of SAGE batch clustering being deprecated
- Commitment can collapse into Belief with source property
- SUPPORTS redundant with DERIVED_FROM
- Entity is RAG feature, not coherence feature
- Code dependencies are on system being rewritten anyway

**Key insight from Reviewer 2:**
> "The first reviewer is anchored in a system that's being deprecated. The pivot explicitly says 'Drop: SAGE batch pipeline.'"

## Open Questions

1. Does Document vs Observation naming matter? (Document suggests file, Observation suggests event)
2. Should ABOUT be kept or is it redundant with REFERENCES?
3. Do we need a separate edge type for agent-created links vs system-detected?

## MCP Surface (5 tools)

| Tool | Creates | Notes |
|------|---------|-------|
| `remember` | Document | Optional REFERENCES |
| `learn` | Claim | REFERENCES to evidence |
| `recall` | - | Query with coherent view |
| `trace` | - | Walk provenance edges |
| `tick` | - | Engagement signal |

Removed: `decide`, `accept`, `dismiss`, `hypothesize`, `commit`, `revise`, `link`, `reflect`, `reason`, `history`, `forget`, `patterns`

Some may return as convenience wrappers (e.g., `link` for explicit edges).

## Intelligence Layer: Passive Observation Model

**Decision:** Option D - Passive Intelligence Layer

Based on Universe Routing paper (arXiv:2603.14799): epistemic state can be detected from behavioral signals, not declared by the agent.

### Core principle

- **No agent-facing write tools** (kill hypothesize, reason, commit)
- **Passive observation** by system
- **Automatic node creation** by SAGE dreaming
- **Smart surfacing** via recall

### What to track automatically

| Signal | What it indicates | Created node |
|--------|-------------------|--------------|
| Action repetition | Stuck/confused state | StuckIndicator |
| Confidence trajectory | Certainty drift | EpistemicState |
| Contradiction rate | Conflicting beliefs | ConflictCluster |
| Resolution pattern | What unblocked agent | Breakthrough |

### Intelligence nodes (passive, system-created)

| Node | Purpose | Created by |
|------|---------|------------|
| EpistemicState | Snapshot of agent certainty/confusion | SAGE observes confidence patterns |
| ReasoningTrace | Compressed action sequence | SAGE compacts session |
| Breakthrough | What resolved a stuck state | SAGE detects confidence spike after struggle |

### Intelligence edges

| Edge | Purpose |
|------|---------|
| OBSERVED_IN | EpistemicState → session/task context |
| RESOLVED_BY | StuckIndicator → Breakthrough |

### How recall surfaces it

Recall returns epistemic context, not just facts:

> "When you last worked on problems like this, you got stuck on Y. The breakthrough came when you tried Z."

### What's killed from current Intelligence layer

| Old | Disposition |
|----|-------------|
| ReasoningChain | Replace with ReasoningTrace (simpler, passive) |
| QueryContext | Kill (debugging only, not memory) |
| WorkingHypothesis | Kill (agent doesn't hypothesize, just decides) |
| TRACED_FROM | Kill (use OBSERVED_IN instead) |
| CONSENSUS_FROM | Kill (multi-chain not needed) |
| hypothesize tool | Kill |
| commit tool | Kill |
| revise tool | Kill |
| reason tool | Kill |

### Implementation priority

Phase 1 (MVP): Skip Intelligence layer entirely. Focus on Memory/Knowledge/Wisdom.

Phase 2 (post-benchmark): Add passive observation. Track:
- Session action patterns
- Confidence drift
- Contradiction frequency
- Resolution patterns

Phase 3 (if valuable): Surface via recall. "You've been here before..."

## Open Questions

1. Should Memory node have subtypes (observation, preference, event) or just a `type` field?
2. Should Commitment have `stale` status field for the engagement surface, or keep StaleCommitment as separate marker?
3. How does `decide` work without the hypothesize/commit flow? Direct write to Commitment?
