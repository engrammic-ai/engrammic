# Whitepaper Outline: The Context Pollution Problem

Working title: "Context Pollution in Memory-Augmented Agents: The Problem and How to Solve It"

## Abstract

Memory-augmented LLM agents accumulate context over time. Without active maintenance, this context becomes polluted - contradictions accumulate, stale beliefs persist, and toxic framing launders through compression. We present the context pollution problem, survey recent research on state contamination, and introduce a write-gated memory architecture that prevents pollution at the source.

## 1. Introduction

- The promise of memory-augmented agents (long-horizon, multi-session, autonomous)
- The hidden failure mode: context pollution
- Why retrieval accuracy isn't enough

## 2. The Context Pollution Problem

### 2.1 What is context pollution?

- Contradictory facts accumulating (mem0 issue #4573: 808 duplicate facts)
- Stale beliefs persisting after correction
- Hallucinations stored as facts, retrieved as truth
- Toxic/adversarial framing persisting through summarization

### 2.2 Why current memory systems fail

- ADD-only architectures (no revision, no supersession)
- Retrieval-focused (find relevant, not find correct)
- No write-time validation
- Batch cleanup too slow (beliefs stabilize within rounds)

### 2.3 The scale of the problem

- mem0 GitHub issues: #4573 (97.8% junk rate), #4896 (ADD-only fails contradictions), #5330 (no stale decay)
- MemoryArena benchmark: 40-60% collapse from retrieval to agentic tasks
- HaluMem (arXiv:2511.03506): hallucination accumulation is systematic

## 3. Research Foundations

### 3.1 State Contamination (Wang et al., 2026)

- Memory laundering: toxic content compressed below classifier threshold
- Sub-threshold propagation gap (SPG = 0.140)
- Key finding: sanitization must happen BEFORE compression

### 3.2 Belief Consistency (Xu et al., 2026)

- Neighborhood Consistency Belief (NCB)
- Structurally grounded vs isolated memorization
- High NCB = robust, Low NCB = brittle (even if surface-correct)

### 3.3 Collective Belief Dynamics (He et al., 2026)

- Beliefs stabilize within few interaction rounds
- Batch detection too slow - already self-sustaining
- Graph-level anomaly detection > content-level

### 3.4 Faithful Reasoning (Yuan et al., 2026)

- SAVER: typed violation taxonomy
- Gate before commit, not after
- Minimal repair, not regeneration

## 4. The Solution: Write-Gated Memory

### 4.1 Core principle

- Pollution prevention, not pollution cleanup
- Gate at write time, before compression
- The write path is where coherence is won or lost

### 4.2 Architecture

```
Agent
  |
Write Gate (intercept, validate, route)
  |-- Epistemic classification (memory/knowledge/wisdom)
  |-- Contradiction detection
  |-- Neighborhood consistency check
  |-- Contamination screening
  |
Persistent Store (with provenance)
  |
Read Path (coherent worldview, not raw nodes)
```

### 4.3 Tiered validation

| Layer | Validation | Rationale |
|-------|-----------|-----------|
| Memory | Light (contradiction only) | Observations, low stakes |
| Knowledge | Deterministic (contradiction, circular, precondition) | Claims need evidence |
| Wisdom | Full audit before synthesis | Compression = laundering locus |

### 4.4 Key mechanisms

- **Supersession chains**: old beliefs yield to new with typed reason
- **Dependency propagation**: update A, re-evaluate everything derived from A
- **Provenance tracking**: every belief traceable to evidence
- **Temporal versioning**: what was believed when, and why it changed

## 5. Evaluation

### 5.1 Metrics

- Contradiction rate over N sessions
- Revision accuracy (does correction propagate?)
- Contamination resistance (SPG under adversarial input)
- Retrieval relevance (LoCoMo, LongMemEval)

### 5.2 Comparison

| Capability | mem0 | Hindsight | ByteRover | Ours |
|------------|------|-----------|-----------|------|
| Revision | LLM-decided reactive | Batch consolidation | Git-like manual | Real-time write-gate |
| Dependency cascade | No (MEME: "near floor") | Partial (background) | Not documented | Yes |
| Contamination screening | No | No | No | Yes (pre-compression) |
| Tiered validation | No | No | No | Yes |

**What we're measuring:**
- Cascade accuracy: when fact A changes, do derived beliefs B, C update?
- Contamination resistance: SPG under adversarial memory injection
- Contradiction accumulation: rate over N sessions
- Latency impact: write path overhead vs baseline

**Honest trade-offs:**
- Write-gating adds 50-200ms latency per write
- Competitors can copy any single feature in days-weeks
- The system (all mechanisms together) is the differentiator, not any one part

### 5.3 Results

[To be filled with benchmark data]

## 6. Implementation: Engrammic

- Open source primitives (schema, edge types, confidence math)
- MCP interface for agent integration
- Managed service with write-gated storage
- Self-hosted option

## 7. Limitations and Future Work

- LLM-based audit adds latency (tiered approach mitigates)
- Adversarial robustness under active attack
- Multi-agent consensus protocols
- Cross-silo belief coordination

## 8. Conclusion

Memory-augmented agents need more than retrieval. They need memory that doesn't pollute itself. Write-gated architectures, informed by state contamination research, provide the foundation for agents that accumulate understanding rather than garbage.

---

## HN Launch Angle

**Title options:**
- "We built memory that doesn't rot"
- "The context pollution problem in AI agents (and how we fixed it)"
- "Why your agent contradicts itself after 10 sessions"

**Key hooks:**
- Research-backed (cite the papers)
- Real problem (link to mem0 issues)
- Open source (primitives available)
- Novel architecture (write-gate, not retrieval)

**Show HN format:**
- Problem statement (3 sentences)
- What we built (2 sentences)
- How it works (bullet points)
- Benchmarks (numbers)
- Open source link
- Try it link
