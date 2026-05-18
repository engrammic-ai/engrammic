# Concepts: Emergent Abstractions for Knowledge Graphs

## Overview

Concepts are emergent abstract nodes that organize knowledge without asserting conclusions. Unlike Beliefs (synthesized judgments) or Patterns (recurring behavioral shapes), Concepts serve as semantic lenses that group related knowledge across domains.

**Primary use case:** Scaling optimization for retrieval quality. As knowledge bases grow, embedding similarity and keyword overlap become insufficient for surfacing conceptually related but surface-dissimilar knowledge. Concepts provide semantic bridging.

**Example:** Facts about "cache TTLs" and "database read replicas" share no keywords, but both relate to a Concept like "read optimization". Querying for stale data handling can surface facts connected to a Consistency Concept even without vocabulary overlap.

## Status

Design spec only. Implementation deferred until concrete evidence of retrieval quality degradation at scale (likely post-closed-beta).

## Node Definition

**Layer:** Wisdom (alongside Belief, Pattern, ProposedBelief)

**Characteristics:**
- Emergent and seedable, not user-declared at runtime
- Evolves in place (no SUPERSEDES chains like Beliefs)
- Soft and hard prunable by users

**Schema:**

```python
class ConceptLabel(StrEnum):
    CONCEPT = "Concept"

# Node properties
{
    "id": str,                    # UUID
    "silo_id": str,               # Multi-tenancy
    "name": str,                  # Human-readable label ("distributed caching")
    "description": str,           # What this concept means in context
    "embedding": list[float],     # For similarity matching
    "confidence": float,          # Coherence score from formation (0.0-1.0)
    "formation_method": str,      # "seed" | "cluster" | "llm_extraction"
    "status": str,                # "active" | "pruned"
    "created_at": datetime,
    "updated_at": datetime,
}
```

## Edge Types

All Concept edges carry a `weight` property (0.0-1.0) representing connection strength.

| Edge | Direction | Meaning |
|------|-----------|---------|
| `RELATES_TO` | `(:Fact\|Claim)-[:RELATES_TO]->(:Concept)` | Concrete knowledge relates to abstract idea |
| `TOUCHES` | `(:ReasoningChain)-[:TOUCHES]->(:Concept)` | Reasoning engaged with this concept |
| `SUBSUMES` | `(:Concept)-[:SUBSUMES]->(:Concept)` | Concept hierarchy ("caching" subsumes "TTL strategies") |
| `ABOUT` | `(:Belief\|Pattern)-[:ABOUT]->(:Concept)` | Synthesized judgment/pattern concerns this concept |

**Weight semantics:**
- High (0.8-1.0): Core relationship, fundamentally about this concept
- Medium (0.4-0.7): Relevant but not central
- Low (0.1-0.3): Tangentially related, useful for broad queries

## Configuration

Thresholds are configurable per deployment:

```yaml
concepts:
  thresholds:
    weak: 0.3           # Below this, don't create edge
    medium: 0.6         # Weak-medium boundary
    strong: 0.85        # Medium-strong boundary
  formation:
    min_cluster_size: 5         # Minimum nodes to trigger concept formation
    min_confidence: 0.6         # Minimum coherence score to create concept
    enabled: false              # Feature flag for rollout
```

## Formation

Concepts emerge via the **Weaver**, a new SAGE persona dedicated to concept management.

**Formation methods:**
- `seed`: Admin-provided domain concepts via migration/seed script
- `cluster`: Weaver detects dense clusters of Facts/Claims sharing embedding similarity
- `llm_extraction`: Weaver identifies abstract concepts during knowledge synthesis

## The Weaver (SAGE Persona)

The Weaver is a dedicated SAGE persona responsible for the full concept lifecycle.

### Responsibilities

| Function | Description |
|----------|-------------|
| **Detection** | Monitor knowledge graph for concept formation opportunities |
| **Formation** | Create new Concepts when triggers fire |
| **Naming** | Generate human-readable names and descriptions via LLM |
| **Linking** | Create and weight edges between Concepts and knowledge nodes |
| **Maintenance** | Prune low-value concepts, merge near-duplicates, update confidence scores |
| **Health reporting** | Surface concept quality metrics for observability |

### Triggers

The Weaver activates on:

1. **Cluster density trigger:** When N+ Facts/Claims cluster in embedding space without an existing Concept covering them
2. **Co-retrieval trigger:** When the same set of nodes are repeatedly retrieved together across queries
3. **Scheduled sweep:** Periodic full-graph analysis for missed opportunities and health maintenance
4. **Manual seed:** Admin-initiated concept seeding via migration script

### Formation Pipeline

```
Trigger fires
    -> Candidate identification (clustering / co-retrieval analysis)
    -> Coherence scoring (is this a real concept or noise?)
    -> LLM naming (generate name + description)
    -> Concept node creation
    -> Edge creation (RELATES_TO edges to constituent nodes)
    -> Hierarchy detection (SUBSUMES edges to parent/child Concepts)
```

### Maintenance Operations

| Operation | Trigger | Action |
|-----------|---------|--------|
| **Prune** | Concept has < K edges after decay | Soft prune (set status: pruned) |
| **Merge** | Two Concepts have high embedding similarity + overlapping edges | Merge into one, update edges |
| **Reweight** | Edge access patterns shift | Adjust edge weights based on retrieval utility |
| **Rename** | Concept scope has drifted | Re-run LLM naming with current constituent nodes |

### Integration with Other SAGE Personas

- **Synthesizer:** When forming Beliefs, Weaver may identify relevant Concepts to link via ABOUT edges
- **Custodian:** During extraction, Weaver may detect concept candidates from new Claims
- **Validator:** Weaver respects validation state (doesn't link to rejected ProposedBeliefs)

### Dagster Integration

The Weaver runs as Dagster assets/jobs:

- `weaver_sweep`: Scheduled periodic sweep for formation and maintenance
- `weaver_on_synthesis`: Triggered after synthesis jobs to check for new concept opportunities
- `weaver_health`: Scheduled health check and metrics emission

## Pruning

**Soft prune (default):**
- Sets `status: pruned`
- Edges remain for provenance
- Excluded from retrieval scoring

**Hard prune (explicit user request):**
- Node and edges deleted
- Follows existing erasure cascade rules
- Logged in audit layer

## Retrieval Integration

When Concepts are active, retrieval can:
1. Expand queries via Concept connections (query matches Concept, pull in RELATES_TO nodes)
2. Score Concept-connected nodes higher when query has conceptual overlap
3. Use SUBSUMES hierarchy for broader/narrower query expansion

Retrieval algorithm changes deferred to implementation.

## Supersession Handling

Concepts use the current CITE supersession behavior:
- Edges to superseded nodes remain immutable for provenance
- Query-time handling walks SUPERSEDES chains to find current versions
- Future improvement (supersession head pointer) may optimize this later

## What Concepts Are Not

- **Not Entities:** Entities are concrete identity anchors (Redis, auth service). Concepts are abstract ideas.
- **Not Beliefs:** Beliefs are synthesized judgments that assert conclusions. Concepts organize without asserting.
- **Not Patterns:** Patterns are recurring behavioral shapes. Concepts are semantic groupings.
- **Not user-authored:** Users cannot create Concepts at runtime. They can prune them.

## Cross-Layer Nature

While Concepts live in the Wisdom layer, they connect across layers:

- **Knowledge layer:** Facts and Claims link to Concepts via RELATES_TO
- **Intelligence layer:** ReasoningChains link to Concepts via TOUCHES
- **Wisdom layer:** Beliefs and Patterns link to Concepts via ABOUT

This makes Concepts a cross-cutting organizational structure, similar to how Commitment spans Knowledge structure with Wisdom semantics. The difference is that Concepts are purely emergent (no agent authorship) and serve as lenses rather than assertions.

## Success Criteria

When implemented, Concepts should:
1. Improve recall on queries where relevant knowledge lacks vocabulary overlap
2. Not degrade retrieval latency beyond acceptable thresholds (TBD)
3. Form coherent, human-interpretable abstractions (subjective quality check)
4. Maintain reasonable concept count (not proliferate into noise)

## Implementation Phases

Implementation follows an incremental development curve. Each phase has its own plan file, coordinated by a master plan.

### Master Plan

`context/plans/concepts-master.md` coordinates the phases and tracks overall progress.

### Phase 1: Schema and Seeding

**Plan file:** `context/plans/concepts-phase1-schema.md`

**Scope:**
- Add `Concept` to `WisdomLabel` enum in primitives
- Add `RELATES_TO`, `TOUCHES`, `SUBSUMES` to edge types
- Extend `ABOUT` edge to support Concepts
- Create Concept node schema with all properties
- Build seed script for admin-provided domain concepts
- Basic CRUD operations for Concepts (no formation logic yet)

**Exit criteria:** Can manually seed Concepts and link them to existing nodes.

### Phase 2: Basic Formation

**Plan file:** `context/plans/concepts-phase2-formation.md`

**Scope:**
- Implement cluster-based concept detection
- LLM naming pipeline (name + description generation)
- Basic Weaver Dagster job for scheduled sweeps
- Formation threshold configuration
- Edge weight assignment on creation

**Exit criteria:** Weaver can autonomously form Concepts from clustered knowledge.

### Phase 3: Retrieval Integration

**Plan file:** `context/plans/concepts-phase3-retrieval.md`

**Scope:**
- Query expansion via Concept connections
- Concept-aware retrieval scoring
- SUBSUMES hierarchy traversal for broader/narrower queries
- Performance benchmarking against targets

**Exit criteria:** Retrieval demonstrably improves on conceptually-related queries.

### Phase 4: Maintenance and Health

**Plan file:** `context/plans/concepts-phase4-maintenance.md`

**Scope:**
- Concept pruning (soft and hard)
- Concept merging for near-duplicates
- Edge reweighting based on access patterns
- Health metrics and telemetry
- Admin UI for concept management (if applicable)

**Exit criteria:** Concepts are self-maintaining and observable.

### Phase 5: Advanced Formation

**Plan file:** `context/plans/concepts-phase5-advanced.md`

**Scope:**
- Co-retrieval trigger implementation
- LLM extraction during synthesis
- Hierarchy detection (automatic SUBSUMES creation)
- Cross-SAGE integration (Synthesizer, Custodian hooks)

**Exit criteria:** Full Weaver capabilities as specified.

## Open Questions

Deferred to implementation phases:
1. Exact clustering algorithm for formation (Phase 2)
2. LLM prompt design for naming/describing concepts (Phase 2)
3. Concept merging strategy for near-duplicates (Phase 4)
4. Retrieval algorithm changes for concept-aware scoring (Phase 3)
5. Telemetry and observability for concept health (Phase 4)
