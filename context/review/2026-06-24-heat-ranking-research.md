# Heat and Ranking Research Review

Date: 2026-06-24

Research into heat-based ranking, temporal retrieval, and memory scoring for contextual relevance. Focused on what's borrowable for Engrammic's recall and cache optimization.

## Current State

Engrammic heat scoring:
- Range: 0 to 1
- Tiers: HOT >= 0.66, WARM >= 0.33, COLD < 0.33
- Formula: `heat = min(1.0, decayed_prior + log(1 + weighted_count) / log(1 + max_count))`
- Decay: exponential, 7-day half-life
- Used for: cache filtering, materialization depth

Gap: heat is separate from recall ranking. PPR and heat run independently.

## Research Findings

### HippoRAG 2 (NeoCognition / OSU)

Paper: [From RAG to Memory: Non-Parametric Continual Learning for LLMs](https://arxiv.org/abs/2502.14802)

Architecture:
- Dual-node graph: phrase nodes + passage nodes
- PPR with biased seeds from query-triple matching
- Synonymy edges at similarity threshold 0.8

Edge weights:
```
Relation edges: w_so = 1
Synonym edges: w_ij = sim(e_i, e_j), threshold τ = 0.8
Context edges: w_dp = 1
```

Key insight: fuse dense (passage) + sparse (phrase) retrieval via graph structure, let PPR propagate relevance.

### TG-RAG (Temporal GraphRAG)

Paper: [RAG Meets Temporal Graphs](https://arxiv.org/abs/2510.13590)

Scoring formulas:
```
Edge score: s(ε) = 𝟙[τ ∈ T^q] · (s(v₁) + s(v₂))
Chunk score: s(c) = w(c) · Σ s(ε)
Weight: w(c) = Π (1 + γ_ε)
Similarity: γ_ε = cos(e_q, e_ε)
```

Algorithm (Local Retrieval):
1. `s(v) ← PPR(G, V_seed)` with temporally filtered seeds
2. `s(ε) ← 𝟙[τ ∈ T^q] · (s(v₁) + s(v₂))` edge scores
3. `s(c) ← Π(1 + γ_ε) · Σ s(ε)` chunk scores

Key insight: binary temporal gating (in/out of time scope) rather than smooth decay. Time filtering happens before PPR, not after.

### ENGRAM (Conversational Agents)

Paper: [ENGRAM: Effective, Lightweight Memory Orchestration](https://arxiv.org/abs/2511.12960)

Architecture:
- 3 memory types: episodic, semantic, procedural
- Router produces 3-bit mask for store selection
- Retrieval: TopK cosine per store, K=25
- Aggregation: `Truncate(Dedup(union(stores)))`

No heat, no decay, no graphs. Just typed stores + dense retrieval. Claims 15pts over full-context baseline on LongMemEval using ~1% tokens.

Key insight: careful memory typing + simple retrieval can beat complex architectures.

### REMem (NeoCognition / OSU)

Paper: [REMem: Reasoning with Episodic Memory](https://arxiv.org/abs/2602.13530)

Architecture:
- Hybrid graph: gist nodes (event summaries) + phrase nodes (fact triples)
- Temporal qualifiers: point_in_time, start_time, end_time
- Synonymy edges at 0.8 threshold
- Agentic inference with explicit time-range tools

Tools:
| Type | Name | Args |
|------|------|------|
| Retrieval | semantic_retrieve | query, start_time, end_time, operators |
| Retrieval | lexical_retrieve | query, start_time, end_time, operators |
| Graph | find_gist_contexts | gist_id, time filters |
| Graph | find_entity_contexts | subject, predicate, object, time filters |

Results: 92.2% EM on Test of Time (vs HippoRAG 2: 74.0%, Mem0: 41.0%)

Key insight: explicit temporal tools beat implicit decay for episodic memory. Agent decides time scope.

### DeepSeek Engram

Paper: [Conditional Memory via Scalable Lookup](https://arxiv.org/abs/2601.07372)

Architectural approach (not retrieval):
- Separate static memory from reasoning
- Multi-head hashing into prime-sized buckets
- Context-aware gating (0 to 1 scalar)
- U-shaped scaling law: optimal at 20-25% sparse budget to Engram

Key insight: memory lookup can be constant-time via hashing, separate from transformer compute.

### Fusion Research (General)

RRF formula: `score = Σ 1/(k + rank_i)` across multiple retrieval methods

Recency + frequency combo (LRFU):
```
score = frequency + prior_score * 0.5^(λ * age_seconds)
λ = 0.5: frequency-heavy
λ = 1.0: balanced
λ = 2.0: recency-heavy
```

## Synthesis

Common patterns across research:

1. **No smooth decay for retrieval** - everyone uses either explicit temporal filtering or graph structure
2. **PPR is the workhorse** - HippoRAG, TG-RAG, and implicitly REMem all use PPR for ranking
3. **Typed memory helps** - ENGRAM's 3 types, REMem's gist+fact, our Memory/Claim/Fact/Belief
4. **Synonymy edges improve multi-hop** - 0.8 threshold is standard

What heat is good for:
- Cache optimization (what to keep warm)
- Implicit importance signal (frequently accessed = likely relevant)
- PPR seed weighting (boost hot nodes in personalization vector)

What heat is NOT good for:
- Temporal retrieval (use explicit time tools or binary gating)
- Replacing graph structure

## Recommendations

### Phase 1: Heat as PPR seed boost

Fuse heat into recall by weighting PPR seeds:
```python
personalization[v] = base_seed[v] * (1 + α * heat[v])
```

Hot nodes get higher reset probability, propagate more influence through graph.

Effort: 1 day
Impact: direct heat-to-recall integration

### Phase 2: Synonymy edges

Add edges between nodes with embedding similarity > 0.8.

**Open decisions:**

| Question | Options | Lean |
|----------|---------|------|
| Timing | on-write (+latency), batch (stale), on-recall (no storage) | on-recall |
| Scope | same-layer only vs cross-layer | same-layer |
| Threshold | 0.8 standard, tunable | 0.8 |
| Edge type | SYNONYM (weight=similarity), participates in PPR | SYNONYM |
| Storage cap | top-K per node if persisted | top-5 |

**On-recall approach (preferred):**
- Query Qdrant for nodes similar to seeds during `_ppr_channel`
- Inject synthetic SYNONYM edges into adjacency
- Zero storage, always fresh, ~50ms added latency
- Batch job could run separately for SAGE dedup purposes

Effort: 2 days
Impact: better recall for related concepts

### Phase 3: Degree normalization

Prevent hub bias in heat accumulation:
```python
heat_contribution = raw_count / log(1 + degree)
```

High-degree nodes don't dominate just because they're central.

Effort: hours
Impact: fairer heat distribution

### Deferred

| Item | Reason |
|------|--------|
| Explicit temporal tools | Parse time from natural language instead |
| Gist extraction | Memory layer already serves this role |
| Separate hash memory | Architectural overhaul, unclear benefit |
| Full agentic inference loop | Adds latency |

## Sources

- [HippoRAG 2](https://arxiv.org/abs/2502.14802) - NeoCognition/OSU
- [TG-RAG](https://arxiv.org/abs/2510.13590) - Hong Kong UST
- [ENGRAM](https://arxiv.org/abs/2511.12960) - Conversational agents
- [REMem](https://arxiv.org/abs/2602.13530) - NeoCognition/OSU (ICLR 2026)
- [DeepSeek Engram](https://arxiv.org/abs/2601.07372) - DeepSeek
- [NeoCognition](https://neocognition.io) - $40M seed, HippoRAG team
- [engram.com](https://engram.com) - $98M, context compression
- [State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) - mem0
