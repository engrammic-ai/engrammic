# Context Pollution in Memory-Augmented Agents

**The Problem and How to Solve It**

*Engrammic Labs, June 2026*

---

## Abstract

Memory-augmented LLM agents accumulate context over time. Without active maintenance, this context becomes polluted: contradictions accumulate, stale beliefs persist, and hallucinations launder through compression. We present the context pollution problem, survey recent research on state contamination and belief dynamics, and introduce a write-gated memory architecture that prevents pollution at the source. On contradiction detection, our system achieves 95% accuracy compared to 66% for retrieval-only baselines. The architecture and implementation are open source under Apache 2.0.

---

## 1. Introduction

Memory-augmented agents represent the path to long-horizon autonomy. An agent that remembers what it learned yesterday can build on that knowledge today. An agent that forgets starts from zero every session.

But memory introduces a hidden failure mode: **context pollution**.

The more an agent remembers, the more opportunities for its memories to contradict each other. A fact stored on Monday conflicts with a fact stored on Tuesday. A correction issued by the user never propagates to the beliefs derived from the original error. A hallucination, once stored, becomes indistinguishable from verified knowledge.

Current memory systems treat this as a retrieval problem: store everything, retrieve the relevant bits, let the LLM sort out the contradictions. This works for a few sessions. It fails catastrophically over time.

This paper argues that context pollution is a **write-path problem**, not a read-path problem. The solution is not better retrieval. The solution is preventing polluted content from being written in the first place.

---

## 2. The Context Pollution Problem

### 2.1 What is Context Pollution?

Context pollution occurs when an agent's memory store accumulates content that degrades reasoning quality:

- **Contradictory facts**: The agent believes both "the API uses OAuth2" and "the API uses API keys"
- **Stale beliefs**: A corrected fact persists alongside its correction, with no mechanism to prefer the newer version
- **Hallucination persistence**: A hallucinated fact, once stored, is retrieved as confidently as verified knowledge
- **Toxic framing persistence**: Adversarial or biased framing survives summarization and compression

### 2.2 Why Current Memory Systems Fail

Most memory systems share a common architecture:

1. Agent produces output containing facts
2. Facts are embedded and stored (ADD-only)
3. On query, relevant facts are retrieved by similarity
4. Retrieved facts are inserted into context
5. LLM reasons over the combined context

This architecture has structural weaknesses:

- **No revision mechanism**: Old facts are never updated, only accumulated
- **No supersession**: When a fact changes, nothing marks the old version as obsolete
- **Retrieval optimizes for relevance, not correctness**: A contradictory fact may score higher on similarity than its correction
- **Batch cleanup is too slow**: By the time a nightly job runs, the wrong belief is already load-bearing in downstream reasoning

### 2.3 The Scale of the Problem

Evidence from production systems:

- **mem0 GitHub issue #4573**: A user reported 808 duplicate facts with a 97.8% junk rate after extended use
- **mem0 GitHub issue #4896**: ADD-only architecture explicitly cannot handle contradictions; issue closed as "not planned"
- **mem0 GitHub issue #5330**: No decay mechanism for stale beliefs; old facts persist indefinitely

Benchmark evidence:

- **MemoryArena**: 40-60% performance collapse when moving from pure retrieval tasks to agentic tasks requiring coherent reasoning
- **HaluMem** (arXiv:2511.03506): Hallucination accumulation is systematic, not random; certain error patterns compound

---

## 3. Research Foundations

Recent research supports the write-gating hypothesis.

### 3.1 State Contamination (Wang et al., 2026)

Wang et al. study "memory laundering" where toxic content compresses below classifier detection thresholds. Key finding: the sub-threshold propagation gap (SPG) is 0.140, meaning 14% of toxic content evades detection after compression.

**Implication**: Sanitization must happen *before* compression, not after. Once content is compressed into memory, it's too late.

### 3.2 Neighborhood Consistency Belief (Xu et al., 2026)

Xu et al. introduce NCB (Neighborhood Consistency Belief), measuring whether a belief is structurally grounded in its local graph neighborhood or isolated.

**Implication**: High-NCB beliefs are robust to perturbation. Low-NCB beliefs are brittle even if surface-correct. Write-time validation should check structural grounding, not just content.

### 3.3 Collective Belief Dynamics (He et al., 2026)

He et al. model how beliefs stabilize in multi-agent systems. Key finding: contradictory beliefs self-sustain within a few interaction rounds.

**Implication**: Batch detection is too slow. By the time a cleanup job runs, the wrong belief is already self-reinforcing. Detection must happen at write time.

### 3.4 SAVER: Faithful Reasoning (Yuan et al., 2026)

Yuan et al. propose SAVER, a typed taxonomy of reasoning violations with minimal repair strategies.

**Implication**: Gate before commit, not after. Repair is more expensive than prevention.

---

## 4. The Solution: Write-Gated Memory

### 4.1 Core Principle

The write path is where coherence is won or lost.

Every write to memory passes through a validation gate. Invalid writes are rejected or corrected before storage. This inverts the traditional architecture: instead of storing everything and filtering on read, we filter on write and trust what's stored.

### 4.2 Architecture

```
Agent
  |
  v
Write Gate
  |-- Epistemic classification (observation / claim / belief)
  |-- Contradiction detection
  |-- Neighborhood consistency check
  |-- Contamination screening
  |
  v
Persistent Store (with provenance)
  |
  v
Read Path (coherent worldview)
```

### 4.3 Tiered Validation

Not all writes need the same scrutiny:

| Layer | Validation | Rationale |
|-------|------------|-----------|
| Memory (observations) | Light: contradiction check only | Low stakes, high volume |
| Knowledge (claims) | Medium: contradiction + evidence required | Claims need grounding |
| Wisdom (beliefs) | Full: contradiction + NCB + dependency audit | Compression = laundering locus |

This tiering balances latency against rigor. Raw observations flow through quickly. Synthesized beliefs get full scrutiny.

### 4.4 Key Mechanisms

**Supersession chains**: When a belief is updated, the old version yields to the new with a typed reason (correction, new evidence, user override). Both versions remain in the graph; queries return the current version while audit trails preserve history.

**Dependency propagation**: When fact A changes, everything derived from A is re-evaluated. A corrected API endpoint propagates to all code examples that referenced it.

**Provenance tracking**: Every belief traces back to its evidence. "The API uses OAuth2" links to the documentation passage that stated it. Beliefs without provenance are flagged as ungrounded.

**Temporal versioning**: The system tracks what was believed when, and why it changed. This enables debugging ("why did the agent think X on Tuesday?") and rollback.

---

## 5. Evaluation

### 5.1 Metrics

We evaluate on four dimensions:

1. **Contradiction detection accuracy**: Given a new fact, does the system correctly identify conflicts with existing beliefs?
2. **Revision propagation**: When a fact is corrected, do derived beliefs update?
3. **Contamination resistance**: Under adversarial input, does polluted content enter the store?
4. **Latency overhead**: What does write-gating cost in wall-clock time?

### 5.2 Experimental Setup

We constructed a test corpus of 500 session transcripts from coding agents, annotated for:
- Contradictions (fact A conflicts with fact B)
- Corrections (fact B supersedes fact A)
- Hallucinations (fact A has no grounding in source material)

Baseline: vanilla embedding-based memory with no write-time validation (representative of mem0-style architectures).

### 5.3 Results

| Metric | Baseline | Engrammic | Delta |
|--------|----------|-----------|-------|
| Contradiction detection | 66% | 95% | +29pp |
| Revision propagation | 12% | 87% | +75pp |
| Contamination blocked | 0% | 73% | +73pp |
| Write latency (p50) | 15ms | 180ms | +165ms |

**Contradiction detection**: The baseline detects obvious contradictions (same subject, opposite predicate) but misses semantic contradictions and transitive conflicts. Write-gating catches both.

**Revision propagation**: The baseline has no propagation mechanism; the 12% represents cases where the retriever happens to return the newer fact. Write-gating explicitly propagates corrections through the dependency graph.

**Contamination blocked**: The baseline stores all writes without validation. Write-gating rejects 73% of adversarial injections (hallucinated facts, circular references, ungrounded claims).

**Latency trade-off**: Write-gating adds ~165ms median latency per write. For high-frequency observation streams, this adds up. For knowledge and belief writes (lower volume, higher stakes), this is acceptable.

### 5.4 Limitations of This Evaluation

- **Internal test suite**: These results are from our annotated corpus, not a public benchmark. LongMemEval-V2 has an empty leaderboard; we will submit once methodology stabilizes.
- **Single-agent focus**: We have not yet evaluated multi-agent scenarios where agents hold conflicting beliefs.
- **Adversarial robustness**: Our contamination screening catches naive attacks; sophisticated adversarial inputs may evade detection.

---

## 6. Implementation: Engrammic

Engrammic is the open-source implementation of write-gated memory.

**engrammic-primitives** (Apache 2.0): The schema library defining node types (Memory, Claim, Fact, Belief), edge types (DERIVED_FROM, SUPERSEDES, CONTRADICTS), and confidence propagation math. Use this standalone if you want the data model without the full backend.

**context-service** (Apache 2.0): The full backend including:
- MCP server for agent integration
- FastAPI admin surface
- Memgraph graph store for provenance and relationships
- Qdrant vector store for similarity retrieval
- SAGE pipeline (custodian, synthesizer) for background maintenance

Both are available at github.com/engrammic-ai.

**Quick start**:
```bash
git clone https://github.com/engrammic-ai/context-service
cd context-service
just up    # Start Docker stack
just dev   # Start MCP server
```

---

## 7. Limitations and Future Work

**Latency**: Write-gating adds 50-200ms per write. For observation-heavy workloads, this accumulates. We're exploring async validation for low-stakes writes.

**LLM cost**: Contradiction detection uses an LLM call. Tiered validation mitigates this (light validation for observations, full audit for beliefs), but costs scale with write volume.

**Multi-agent consensus**: When two agents hold conflicting beliefs, the current system has no arbitration mechanism. This is specced but not built.

**Cross-silo coordination**: Beliefs are scoped to a single silo (tenant). Cross-silo belief sharing requires trust mechanisms we haven't designed.

**Adversarial robustness**: Contamination screening catches naive attacks. A determined adversary crafting inputs to evade detection is an open problem.

---

## 8. Conclusion

Memory-augmented agents need more than retrieval. They need memory that doesn't pollute itself.

The context pollution problem is structural: ADD-only architectures accumulate contradictions, stale beliefs persist, and hallucinations launder through compression. Research on state contamination, belief dynamics, and faithful reasoning converges on a single insight: sanitization must happen at write time, before compression, not after.

Write-gated memory inverts the traditional architecture. Instead of storing everything and filtering on read, we filter on write and trust what's stored. The result: 95% contradiction detection (vs 66% baseline), 87% revision propagation (vs 12%), and 73% contamination blocking (vs 0%).

The architecture is open source. We invite the community to build on it.

---

## References

1. Wang et al. (2026). "State Contamination in Long-Context LLMs." arXiv:2605.16746
2. Xu et al. (2026). "Neighborhood Consistency Belief for Knowledge Graph Robustness." arXiv:2601.05905
3. He et al. (2026). "Collective Belief Dynamics in Multi-Agent Systems." arXiv:2605.19915
4. Yuan et al. (2026). "SAVER: Faithful Reasoning through Typed Violation Detection." arXiv:2604.08401
5. mem0 GitHub issues #4573, #4896, #5330. https://github.com/mem0ai/mem0/issues
6. HaluMem benchmark. arXiv:2511.03506

---

*Engrammic is developed by Engrammic Labs. Contact: hello@engrammic.ai*
