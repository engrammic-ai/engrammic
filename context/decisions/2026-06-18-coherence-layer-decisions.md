# Anti-Context-Pollution Architecture Decisions

Date: 2026-06-18
Status: Decided
Related: [Brainstorm](../brainstorm/2026-06-18-coherence-layer-pivot.md), [Whitepaper Outline](../brainstorm/2026-06-18-context-pollution-whitepaper-outline.md)

## Context

Strategic reframe (not pivot): Engrammic is still a memory layer, but differentiated by **anti-context-pollution**. The coherence layer is internal architecture; the pitch is "memory that doesn't rot." Validated by 6 research papers, market gap analysis, and state contamination research.

Key insight: "Memory/context" is the category people understand. Truth maintenance, write-gate, dependency propagation are mechanisms. The differentiator is the outcome: your agent's context doesn't pollute itself.

## Decisions

### 1. SAVER Audit-Repair: Tiered by Layer

**Decision:** Option B - tiered checking by layer.

| Layer | Check Type | What |
|-------|-----------|------|
| Memory | Light | Contradiction detection only |
| Knowledge | Deterministic | Contradiction, circular reasoning, precondition validity |
| Wisdom | Full audit | LLM-based before synthesis (laundering locus) |

**Rationale:** State contamination paper (arXiv:2605.16746) shows sanitization must happen BEFORE compression into persistent memory. SAGE synthesizer is exactly the compression step. Tiered approach balances performance with safety.

**Commitment ID:** `cd1c15d5-5690-4fbb-8bac-29a68322025d`

---

### 2. Cold Storage: Managed Postgres+pgvector

**Decision:** Managed Postgres+pgvector for MVP. BYOB adapters later.

- **MVP:** We run Postgres+pgvector, control write path fully
- **Later:** Add BYOB adapters (Hindsight, mem0) when enterprise demands
- **Model:** Hybrid - managed default, BYOB for enterprise

**Rationale:** 
- 2-person team, need simplicity
- Must control write-gate for contamination prevention
- Postgres simpler than Memgraph+Qdrant
- Less friction for early customers
- Proxy-over-Hindsight adds integration complexity

**Commitment ID:** `bda52a3d-e3d2-400c-b14a-64b55295737e`

---

### 3. Integration Depth: Phased Approach

**Decision:** Start narrow, expand on demand.

| Phase | Scope | Harnesses |
|-------|-------|-----------|
| Phase 1 (MVP) | MCP only | Claude Code, Gemini CLI |
| Phase 2 (post-validation) | Python SDK + REST | OpenClaw, Hermes, CrewAI, LangGraph, OpenAI Agents |
| Phase 3 (demand-driven) | Framework adapters | Only if customers ask |

**Rationale:** MCP already exists, works for demo/validation. No point building adapters nobody asked for.

**Commitment ID:** `dfc0a898-2bab-47ed-b30c-bb253792eae2`

---

### 4. Demo Format: Video + Benchmark + Design Partner

**Decision:** All three, in order.

1. **A - Side-by-side video** (~1 week)
   - Same agent, same workflow, N sessions
   - Left: raw memory - watch it contradict itself
   - Right: Engrammic coherence - stays consistent
   - Show drift quantitatively

2. **C - Benchmark with coherence metrics**
   - Run on existing benchmarks (LoCoMo, MemoryArena)
   - Add coherence-specific metrics: contradiction rate, revision accuracy
   - Technical credibility

3. **D - Design partner dogfood**
   - Real workflow, real contradictions caught
   - Most compelling proof
   - Target: Verda or similar

**Rationale:** Video is visceral and fast. Benchmark adds credibility. Design partner proves real-world value.

**Commitment ID:** `2fb35d8a-0c3e-4e13-9fad-8dfa6fadf581`

---

### 5. Pricing: Tiered Flat + Overage

**Decision:** Simple tiered model, specifics TBD post-MVP.

| Tier | Nodes | Ops/month | Features |
|------|-------|-----------|----------|
| Free | 1K | 10K | Try it |
| Pro | 50K | 100K | Dashboard, support |
| Enterprise | Custom | Custom | BYOB, SLA |

**Rationale:**
- Write-gate LLM audit (Wisdom layer) has real cost
- Graph ops (contradiction check) are cheap
- Value is coherence, not storage
- Tiered model familiar, overage handles heavy usage
- Defer complexity until usage patterns clear

**Commitment ID:** `84fdb9a7-7bb4-4319-8611-9fad21707306`

---

## Research Backing

### Papers Reviewed

1. **Universe Routing** (arXiv:2603.14799)
   - Hard epistemic routing, not soft blending
   - Small classifier (465M) beats 80B+ LLMs
   - Explicit boundary supervision required

2. **Collective Belief Dynamics** (arXiv:2605.19915)
   - Beliefs stabilize within rounds - real-time detection critical
   - Batch too slow, already self-sustaining by detection
   - Graph-level anomaly detection > content-level

3. **Neighborhood Consistency Belief** (arXiv:2601.05905)
   - NCB as write-time quality signal
   - Check prerequisite/implication beliefs before accepting
   - Scale doesn't help - 1.5B to 72B same gap

4. **SAVER** (arXiv:2604.08401)
   - Typed violations: Missing_Assumption, Invalid_Precondition, Unjustified_Inference, Circular_Reasoning, Contradiction, Overgeneralization
   - Minimal repair, not regeneration
   - Gate before commit - 81% violation-free vs 25% CoT

5. **Memory for Autonomous LLM Agents** (arXiv:2603.07670)
   - Consolidation + contradiction = biggest unsolved gaps
   - Write path is where coherence is won or lost
   - MemoryArena shows 40-60% collapse vs LoCoMo

6. **State Contamination** (arXiv:2605.16746)
   - Write-gate before compression is critical
   - Memory laundering: toxic content below classifier threshold still influences
   - SPG = 0.140 even when 99%+ memory states are classifier-clean
   - SAGE synthesizer = compression locus

### Market Gap

| Company | Funding | Gap vs Engrammic |
|---------|---------|------------------|
| Mem0 | $24M | ADD-only, no revision, no coherence |
| Hindsight | $3.5M | Synthesis on demand, not live |
| Cognee | €7.5M | No truth maintenance |
| Letta | Unknown | Context management, not belief |
| Zep | Unknown | No dependency propagation |

Memory systems getting 0.30x capital-to-deal ratio. Coherence is unoccupied category.

### Validated Competitive Gaps (2026-06-18)

| Capability | mem0 | Hindsight | ByteRover | Gap |
|------------|------|-----------|-----------|-----|
| Updates | LLM-decided | Both states + batch | Git-like | All have revision |
| Dependency Cascade | No (MEME: "near floor") | Partial (background) | Not documented | Real gap |
| Contamination Screening | No | No | No | Real gap |
| Tiered Validation | No | No | No | Real gap |

Sources: MEME benchmark (arXiv:2605.12477), OWASP Agentic Top 10 (arXiv:2604.16548v1)

### Defensibility Assessment

**High defensibility (months to copy):**
- Dependency propagation - requires graph schema + provenance throughout
- Tiered validation by epistemic layer - conceptual shift, not feature flag

**Medium defensibility (weeks to copy):**
- Graph anomaly detection - novel application but not hard
- Real-time vs batch consolidation - engineering choice, adds latency

**Low defensibility (days to copy):**
- Write-time contamination screening - just an LLM call before write

**Honest assessment:**
1. No permanent moats. 6-12 months, well-funded competitors can copy any feature.
2. The moat is the combination. Full coherence runtime (routing + gate + NCB + anomaly + propagation) is a system, not a feature.
3. Latency trade-off is real. Write-gating adds 50-200ms. Competitors prioritize speed. This is a product bet.
4. Speed to market matters. First to productize "coherence" owns category. mem0 shipped fast; pivoting is a rewrite.
5. Research backing is temporary shield. Papers validate architecture. By the time competitors study same papers, we're live.

**What actually matters:** The benchmark. If we can't show measurably better coherence on LoCoMo/MemoryArena/MEME, the architecture claims are vapor.

---

## Architecture Summary

```
Agent (Claude Code, CrewAI, etc.)
    |
Engrammic Coherence Layer
    |-- Epistemic Router (hard classification to layer)
    |-- Write Gate (typed violations, tiered by layer)
    |-- Neighborhood Consistency Check
    |-- Graph Anomaly Detection
    |-- Dependency Propagation
    |
Postgres + pgvector (managed)
```

**Keep:** Primitives, MCP surface, layer semantics
**Drop:** Memgraph/Qdrant requirements, SAGE batch pipeline
**Build:** Coherence runtime, real-time violation detection

---

## Next Steps

1. Build MVP demo (~1 week)
   - In-memory coherence graph
   - Basic contradiction detection + tiered audit
   - Postgres+pgvector backend
   - MCP interface (modify existing)

2. Side-by-side video showing coherence vs raw memory

3. Benchmark with coherence-specific metrics

4. Design partner validation (Verda?)

---

## Engrammic Node References

**Commitments:**
- SAVER tiered: `cd1c15d5-5690-4fbb-8bac-29a68322025d`
- Cold storage: `bda52a3d-e3d2-400c-b14a-64b55295737e`
- Integration: `dfc0a898-2bab-47ed-b30c-bb253792eae2`
- Demo format: `2fb35d8a-0c3e-4e13-9fad-8dfa6fadf581`
- Pricing: `84fdb9a7-7bb4-4319-8611-9fad21707306`
- Main pivot: `42b13c4d-cda8-41a9-928b-57972fbdf969`

**Key Memories:**
- Strategic pivot: `a2be0afb-0fd5-409a-9c26-3f9bb519b838`
- Research review: `6198b723-4250-42f9-ba27-144fd55b2489`
- Market analysis: `4c914f8d-faad-4ac5-ae14-61c69671fc97`
- Architecture: `774349ad-20cd-4475-921d-392baefb3996`
- State contamination: `521029bb-0b91-4e7c-ba89-ce25f7368a61`
