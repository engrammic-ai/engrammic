# Anti-Context-Pollution Architecture: Research and Strategy

Date: 2026-06-18
Status: Decided
Updated: Reframed from "pivot" to architectural enhancement

## The Reframe

**We are still a memory layer.** That's the category people understand.

**The differentiator is anti-context-pollution.** Memory that doesn't rot. Memory that actively prevents contamination.

"Coherence layer" is internal architecture. "Truth maintenance" and "write-gate" are mechanisms. The pitch is the outcome: your agent's context stays clean.

### Original north star (from Manifesto)

> "Before an agent can reason, it must be capable of doubt."
> "We are building epistemology for machines. Not a better search engine. Not a memory layer."

### What we built

Storage with epistemic labels. Layers (Memory/Knowledge/Wisdom/Intelligence) with different persistence semantics. Batch coherence via SAGE/Dagster. Good schema, missing runtime.

### What we're adding

**Write-gated memory with anti-pollution mechanisms:**
- Gates writes before beliefs stabilize (research: beliefs self-sustain within rounds)
- Routes epistemically (hard classification by layer)
- Prevents contamination before compression (research: sanitize before, not after)
- Propagates updates through dependencies

## The Paradigm Shift

```
Current paradigm (RAG / Memory):
  Storage stores, Model thinks, Retrieval connects them

Next paradigm (Cognitive Substrate):
  Storage stores, Coherence Layer maintains worldview, Model reasons FROM coherent state
```

The model doubts in the moment (ephemeral). The coherence layer doubts across time (persistent).

## Market Landscape

### Competitors (all building memory, not coherence)

| Company | Funding | Approach | Gap |
|---------|---------|----------|-----|
| Mem0 | $24M Series A | Memory layer, ADD-only | No revision, no coherence |
| Hindsight | $3.5M | 4 networks, Reflect synthesis | Synthesis on demand, not live |
| Cognee | €7.5M | KG + vector + relational | No truth maintenance |
| Letta | Unknown | LLM-as-OS, self-managing | Context management, not belief |
| Zep/Graphiti | Unknown | Temporal supersession | No dependency propagation |

### Funding trend

Agent Memory Systems: 0.30x capital-to-deal ratio (below average). Memory infra seen as commoditizing. Application agents getting bigger checks.

### The gap

Nobody owns "coherence" as the product category. Truth maintenance is academically recognized, not productized.

## Competitive Analysis (Validated 2026-06-18)

### Capability Matrix

| Capability | mem0 | Hindsight | ByteRover | Engrammic |
|------------|------|-----------|-----------|-----------|
| Updates/Revision | Yes (LLM-decided) | Timestamps both states | Git-like versioning | Supersession chains |
| Supersession | Reactive (on write similarity) | Batch consolidation | Manual rollback | Real-time write-gate |
| Dependency Propagation | No | Partial (background) | Not documented | Yes (graph traversal) |
| Contamination Screening | No | No | No | Yes (pre-compression) |
| Tiered Validation | No (all memory same) | No | No | Yes (by epistemic layer) |
| Graph Anomaly Detection | No | No | No | Yes |

Sources:
- mem0 Update Memory docs (https://docs.mem0.ai/core-concepts/memory-operations/update)
- mem0 State of Memory 2026 (https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- ByteRover 2.0 architecture (https://www.byterover.dev/blog/memory-architecture)
- Hindsight: Resolving Memory Conflicts (https://hindsight.vectorize.io/blog/2026/02/09/resolving-memory-conflicts)

### Dependency Propagation Gap

| System | Cascade Updates? | Evidence |
|--------|------------------|----------|
| mem0 | No | "struggles with cascade updates and derived facts, Cascade and Absence metrics near floor" (MEME benchmark, arXiv:2605.12477) |
| Hindsight | Partial | Consolidation pipeline is background job, not real-time |
| ByteRover | Not documented | Has provenance/relations but no cascade mechanism found |

When a source fact changes, derived beliefs should re-evaluate. Nobody does this.

### Contamination Screening Gap

| System | Write-time screening? | Evidence |
|--------|----------------------|----------|
| mem0 | No | No toxicity/contamination check before write |
| Hindsight | No | Consolidation is semantic, not safety |
| ByteRover | No | No safety screening documented |

OWASP classifies memory poisoning as ASI06 in 2026 Top 10 for agentic apps (arXiv:2604.16548v1). State contamination paper (arXiv:2605.16746) shows memory laundering happens. Nobody screens writes.

## Defensibility Analysis

### High defensibility (hard to copy)

**Dependency propagation**
- Requires graph structure with typed edges (they'd need schema migration)
- Requires tracking what's derived from what (provenance throughout)
- Engineering effort: months, not days
- But: once they see it working, they will copy it

**Tiered validation by epistemic layer**
- Requires classifying writes by type (Memory vs Knowledge vs Wisdom)
- Different validation rules per tier
- Conceptual shift, not just a feature flag
- But: could be approximated with simpler heuristics

### Medium defensibility (weeks to copy)

**Graph anomaly detection**
- Requires graph structure (they have this, partially)
- Pattern detection on structure, not content
- Novel application, but not rocket science

**Real-time vs batch**
- Hindsight already does consolidation, just async
- Moving to synchronous is an engineering decision
- Adds latency (their incentive is speed)

### Low defensibility (days to copy)

**Write-time contamination screening**
- Just an LLM call before write
- They could add this tomorrow
- Trade-off: adds latency to every write
- mem0's pitch is speed; this hurts their value prop
- But: if OWASP makes it table stakes, they will add it

### Honest assessment

1. **None of these are permanent moats.** Given 6-12 months, well-funded competitors can copy any of them.

2. **The moat is the combination.** Any single feature is copyable. The full coherence runtime (epistemic routing + write gate + NCB check + graph anomaly + dependency propagation) is a system, not a feature.

3. **The latency trade-off is real.** Write-gating adds 50-200ms per write. Agentic apps are latency-sensitive. We're betting coherence matters more than speed. This is a product bet, not a technical moat.

4. **Speed to market matters.** First to productize "coherence" owns the category positioning. mem0 is ADD-only because that's what shipped fast. They can pivot, but it's a rewrite.

5. **Research backing is the temporary shield.** We cite papers, they ship features. The research validates the architecture before we build it. By the time competitors study the same papers, we're live.

### What actually matters

The benchmark. If we can't show measurably better coherence on LoCoMo/MemoryArena/MEME, the architecture claims are vapor. The mem0 benchmark gates everything.

## Research Findings

### Paper 1: Epistemic Control (Universe Routing)
arXiv:2603.14799

**Core thesis:** Primary failure mode of lifelong agents is inability to select correct reasoning framework before applying it. Mixing epistemically incompatible frameworks produces outputs "axiomatically inconsistent."

**Key findings:**
- Hard routing over soft aggregation - mixing epistemic types is semantically meaningless
- Small boundary-trained classifier (465M) matches 80B-1T cloud models, 88-775x faster
- Explicit ill-posed detection requires training on negative examples
- Modular expansion via rehearsal achieves zero forgetting

**Implication:** Coherence layer needs hard epistemic routing (Memory vs Knowledge vs Wisdom vs Intelligence), not weighted blending. Small classifier, not LLM inference.

### Paper 2: Collective Belief Dynamics
arXiv:2605.19915

**Core thesis:** Belief distributions stabilize within few rounds, creating "consolidation threshold" beyond which induced beliefs become self-sustaining.

**Key findings:**
- Stance entropy (openness to revision) should be structural property of belief nodes
- "Temporal decoupling" - by time conflict detected in batch, already self-sustaining
- Context-dependent resolution - same contradiction needs different handling based on cluster corroboration
- System-level anomaly detection beats content-level validation

**Implication:** Detection must be real-time, not batch. Watch graph structure, not just individual nodes. SAGE's async pipeline is structurally wrong.

### Paper 3: Neighborhood Consistency Belief (NCB)
arXiv:2601.05905

**Core thesis:** Self-consistency (asking same question N times) is superficial. Facts with perfect SC collapsed from 100% to 33.8% under mild pressure.

**Key findings:**
- NCB measures structural grounding - does model also correctly answer related questions?
- High NCB = robust (11-16% drop under stress), Low NCB = brittle (22-26% drop)
- Scale doesn't help - 1.5B to 72B shows no improvement
- Reflection > single-pass CoT for conflict resolution

**Implication:** NCB as write-time quality signal. Check neighborhood consistency before accepting claims. Grounded beliefs resist interference.

### Paper 4: SAVER (Verify Before Commit)
arXiv:2604.08401

**Core thesis:** Coherent-looking reasoning ≠ faithful reasoning. "Unfaithful belief states can propagate, bias decisions, and trigger costly actions."

**Key findings:**
- Consensus-based verification fails (correlated assumptions)
- Typed violation taxonomy (6 types): Missing_Assumption, Invalid_Precondition, Unjustified_Inference, Circular_Reasoning, Contradiction, Overgeneralization
- Minimal counterfactual repair, not full regeneration
- Iterate audit-repair until violations cleared, THEN commit

**Implication:** Pre-write verification hook with typed violations. Return specific repair targets, not just "rejected." 81% violation-free vs 25% for CoT.

### Paper 5: Memory for Autonomous LLM Agents (Survey)
arXiv:2603.07670

**Core thesis:** Comprehensive survey identifying gaps in current memory systems.

**Key findings:**
- "The consolidation gap is the biggest unsolved problem" - no production system implements principled consolidation
- Contradiction detection underbuilt - key metric, no benchmark tests it systematically
- MemoryArena shows 40-60% collapse vs LoCoMo - storing/retrieving ≠ coherent belief state
- Source attribution and provenance near-zero in current systems
- "The write path is where coherence is won or lost"

**Implication:** Validates the gap. Nobody has built this. Write-time gating is where it's won or lost.

## Architecture That Emerges

```
Agent (Claude Code, CrewAI, etc.)
    ↓
Engrammic Coherence Layer
    ├── Epistemic Router (hard classification to layer)
    ├── Write Gate (typed violations, repair targets)
    ├── Neighborhood Consistency Check
    ├── Graph Anomaly Detection
    └── Dependency Propagation
    ↓
Cold Storage (Postgres, Hindsight, whatever)
```

### Core components

1. **Epistemic Router**
   - Hard routing to Memory/Knowledge/Wisdom/Intelligence
   - Small classifier, not LLM inference
   - Trained on boundary examples

2. **Write Gate**
   - Typed violation detection (SAVER taxonomy)
   - Acceptance criteria per violation type
   - Minimal repair targets, not rejection
   - Iterate until clean, then commit

3. **Neighborhood Consistency Check**
   - Before accepting claim, check related beliefs
   - Prerequisites, implications, associations
   - Low NCB = flag for lower confidence

4. **Graph Anomaly Detection**
   - Watch structure, not just nodes
   - Sudden clusters of low-evidence nodes
   - PPR spikes for unsupported conclusions
   - Temporal patterns

5. **Dependency Propagation**
   - When belief changes, find dependents
   - Re-evaluate derived beliefs
   - Confidence flows through graph

### What we keep

- Primitives (schema, edge types, confidence math)
- MCP surface (verbs, tool definitions)
- Layer semantics (Memory/Knowledge/Wisdom/Intelligence)

### What we drop

- Memgraph/Qdrant as requirements (become optional)
- SAGE batch pipeline (replaced by real-time)
- Dual-write complexity

### What we build

- Coherence runtime (the actual product)
- Lightweight coherence graph (SQLite, not Memgraph)
- Backend adapters (Postgres, Hindsight, mem0)
- Real-time violation detection

## Product Positioning

### Entry pitch
"Memory that doesn't rot" (solves acute pain)

### Real pitch
"The next frontier for autonomous agentic memory"

### Technical pitch
"Coherence layer for AI agents. Plug into any memory system. Your agent maintains a coherent worldview."

### What customers get (managed service)

1. Coherent memory out of the box
2. Dashboard - see what agent believes and why
3. Simple integration (MCP, SDK, REST)
4. No ops burden

## Open Questions

1. Cold storage strategy - run our own Postgres, or pure proxy over customer's backend?
2. Pricing model - per-request, per-node, per-agent?
3. Integration depth - MCP only, or SDKs for CrewAI/LangGraph/etc?
4. How much of SAVER's audit-repair loop can be deterministic vs requires LLM?

## Next Steps

1. Build minimal demo showing coherence vs no-coherence on same agent workflow
2. Validate with 1-2 design partners (Verda?)
3. Decide on cold storage strategy
4. Estimate rewrite scope

## References

- [Universe Routing (Epistemic Control)](https://arxiv.org/abs/2603.14799)
- [Collective Belief Dynamics](https://arxiv.org/abs/2605.19915)
- [NCB (Belief Consistency)](https://arxiv.org/abs/2601.05905)
- [SAVER (Verify Before Commit)](https://arxiv.org/abs/2604.08401)
- [Memory for Autonomous LLM Agents](https://arxiv.org/abs/2603.07670)
