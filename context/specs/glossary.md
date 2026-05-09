# Glossary

Service-layer terminology for Engrammic. For EAG layer/transition definitions, see `primitives/context/specs/`.

---

## Custodian Identities

The original Custodian was split into four specialized identities, each owning specific EAG transitions:

| Identity | Role | EAG Transitions | Trigger | Model |
|----------|------|-----------------|---------|-------|
| **Custodian** | Contradiction detection, supersession | T2 | Per-write (async) | haiku |
| **Synthesizer** | Weak synthesis, ProposedBelief creation, revision | T3, T4, T10 | Periodic + threshold | sonnet |
| **Groundskeeper** | Memory lifecycle, decay enforcement, dedup | T6, T9 | Nightly batch | none (deterministic) |
| **Validator** | Reasoning structure validation | T13 | Sync on crystallize | sonnet |

### Custodian

Reactive identity triggered after every `context_store` write. Checks if new Facts contradict existing Facts in the silo. If so, writes `SUPERSEDES` edges (T2). Micro-batched for LLM cost efficiency.

### Synthesizer

Periodic identity that detects when clusters of Facts reach density thresholds. Creates Beliefs (T3) for high-confidence clusters, ProposedBeliefs (T10) for medium-confidence. Also handles evidence-gated revision (T4) when underlying fact distributions shift.

### Groundskeeper

Batch identity responsible for memory hygiene. Manages the lifecycle of Memory-layer nodes according to their decay class (ephemeral/standard/durable/permanent). Enforces hard-delete (T9) for nodes past their decay threshold. Handles trace archival (T6) and lossless hyperedge deduplication. Does not use LLM - all operations are deterministic.

### Validator

Synchronous identity invoked during `context_crystallize`. Validates that a WorkingHypothesis has sound reasoning structure and valid premises before promoting to Commitment. 5s timeout; on timeout, crystallize proceeds with `validation_skipped=True` flag.

---

## Decay Classes

Memory-layer nodes are tagged with a decay class that determines their lifespan:

| Class | Half-life | Hard-delete | Example |
|-------|-----------|-------------|---------|
| ephemeral | 7d | 14d | Transient queries, lunch decisions |
| standard | 90d | 180d | Typical work context |
| durable | 540d | 1080d | Important project decisions |
| permanent | 5y | 10y | Mathematical proofs, core insights |

Groundskeeper enforces these thresholds. Nodes can be upgraded (never downgraded) if they become more important (e.g., get cited, lead to Commitments).

---

## EAG Transition Reference

Quick reference for transitions mentioned above. Full spec in `primitives/context/specs/03-transitions.md`.

| ID | Transition | Description |
|----|------------|-------------|
| T2 | Knowledge supersede | New Fact contradicts existing Fact |
| T3 | Knowledge synthesize | Cluster density threshold reached, create Belief |
| T4 | Wisdom revise | Evidence distribution shifted, update Belief |
| T6 | Intelligence trace | Session ends, reasoning chain traced to Memory |
| T9 | Memory hard-delete | Node past decay threshold, delete |
| T10 | Knowledge propose | Medium confidence, create ProposedBelief |
| T13 | Intelligence crystallize | Agent commits WorkingHypothesis to Commitment |
