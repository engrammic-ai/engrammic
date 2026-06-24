# ML Products for Frontier Labs - Design Spec

## Overview

Two ML products for frontier model companies, sold separately:

| Product | Target | Timeline | GTM |
|---------|--------|----------|-----|
| **Heat Model** | Anyone building agents/RAG | 2-3 months | Open weights first, then enterprise, then frontier |
| **Memory Module** | Frontier labs | 6+ months | Prove on open weights, build momentum, then pitch |

### Strategy: Open Weights First

1. Ship heat model integration for Llama/Mistral
2. Publish benchmarks showing context efficiency gains
3. Memory module follows, same pattern
4. Frontier labs adopt/acquire/partner from position of leverage

### Training Data Approach

- Structural signals only (heat curves, access patterns, graph topology, layer distribution)
- No content leaves customer environments
- Bootstrap with synthetic data, improve with real aggregated patterns
- Per-silo opt-in for training data contribution

---

## Product 1: Heat Model

### Purpose

Predict importance/relevance of knowledge given context. Solves "what goes in the context window" - the "lost in the middle" problem frontier labs face with large context windows.

### Architecture

Temporal Graph Neural Network (TGNN):

```
[Query Embedding] ──┐
                    ├──► [Attention-weighted aggregation] ──► [Relevance Score]
[Node Features] ────┤
  - heat time series
  - layer type (Memory/Knowledge/Wisdom)
  - recency, access frequency
  - graph degree, neighbor avg heat

[Edge Features] ────┘
  - relationship type
  - co-access patterns
  - edge heat
```

Candidate architectures: TGN (Temporal Graph Networks), GraphMixer, or small transformer decoder for final ranking.

### Training Data

| Signal | What it captures | Privacy |
|--------|------------------|---------|
| Heat time series | Importance evolution per node | Numbers only |
| Access patterns | What gets retrieved when | Node IDs + timestamps |
| Graph topology | Evidence chains, supersession depth | Structure only |
| Layer distribution | Memory / Knowledge / Wisdom flow | Type labels |
| Retrieval feedback | What was shown vs. selected | Ranking data |

### Inference

- Input: query embedding + candidate node features
- Output: relevance scores for ranking
- Latency target: <10ms for 1000 candidates

### Delivery

- API for cloud customers
- Weights download for self-hosted / open-weights integration

---

## Product 2: Memory Module

### Purpose

Encode epistemic reasoning - belief formation, revision, provenance. Solves "how do agents maintain coherent beliefs over time" for long-horizon agents.

### What It Encodes

- **Belief formation:** observation / claim / corroborated fact / synthesized belief
- **Belief revision:** supersession chains ("I believed X, now Y because Z")
- **Provenance:** every belief traces to evidence
- **Confidence:** source tier, corroboration count, uncertainty

### Architecture Options

| Approach | Pros | Cons |
|----------|------|------|
| **Adapter/LoRA** | Plugs into existing models, small | Per-architecture integration |
| **State-space (Mamba-style)** | O(1) lookup, efficient | Less expressive |
| **Reasoning trace encoder** | Explicit supersession modeling | Higher latency |

Initial approach: Adapter/LoRA for lowest integration friction.

### Training Data

| Signal | What it teaches |
|--------|-----------------|
| Supersession chains | How beliefs update |
| Evidence / claim links | Grounding patterns |
| Layer transitions | Epistemic maturity flow |
| Provenance graphs | Citation structure |

### Integration Pattern

```
[Base LLM] ←──cross-attend──► [Memory Module]
                                    ↑
                              [Engrammic store]
                              (beliefs, provenance, heat)
```

### Delivery

- Reference integration for Llama 3/4
- Adapter weights + integration guide
- API option for hosted inference

---

## Data Capture (context-service instrumentation)

### New Storage

| Table | Fields | Purpose |
|-------|--------|---------|
| `heat_snapshots` | node_id, heat_score, timestamp, silo_id | Heat time series |
| `access_events_archive` | node_id, event_type, timestamp, query_embedding_hash | Long-term access patterns |
| `retrieval_feedback` | query_id, shown_node_ids, selected_node_ids, timestamp | What was shown vs clicked |
| `graph_snapshots` | node_id, degree, neighbor_avg_heat, layer, timestamp | Periodic graph topology capture |

### Instrumentation Points

| Where | What to capture |
|-------|-----------------|
| `recall` tool | Query embedding hash, results shown, result selected (if feedback enabled) |
| Heat diffusion job | Snapshot heat scores before/after each run |
| `remember`/`learn` | New node features at creation time |
| `link` | Edge creation events |

### Privacy Controls

- No content stored - only IDs, scores, timestamps, hashes
- Per-silo opt-in for training data contribution
- Aggregation before export (no single-tenant data leaves)

### Export Pipeline

- Dagster job to export anonymized training batches
- Destination: GCS bucket or direct to training infra

---

## Synthetic Data Generation (spec only)

### Heat Model Synthetic Data

| Pattern | How to generate |
|---------|-----------------|
| Access bursts | Simulate "project starts" - cluster of nodes accessed together |
| Decay curves | Exponential decay with noise, varying by layer type |
| Graph diffusion | Simulate heat spreading through random graphs |
| Seasonal patterns | Weekly/daily cycles in access |

### Memory Module Synthetic Data

| Pattern | How to generate |
|---------|-----------------|
| Belief formation | observation / claim / evidence / fact chains |
| Supersession | Correct belief revision sequences |
| Incorrect revision | Anti-examples (model should reject) |
| Provenance chains | Claims with varying evidence depth/quality |
| Confidence calibration | High evidence = high confidence, low evidence = low confidence |

### Generation Approach

1. Define templates based on EAG/CITE principles
2. Parameterize with realistic distributions
3. Generate at scale (100k+ examples)
4. Validate with human spot-checks

### Tooling

- Python generator in `src/context_service/ml/synthetic/`
- Config-driven (adjust distributions without code changes)
- Output: Parquet files for training

---

## Benchmarks and Validation

### Heat Model Benchmarks

| Benchmark | What it measures |
|-----------|------------------|
| **Context efficiency** | Same task accuracy with N% less context (prioritized by heat) |
| **Retrieval ranking** | nDCG/MRR vs baseline (recency, BM25, embedding similarity) |
| **Latency** | Inference time for 1k candidates |
| **Cold start** | Performance on new silos with no history |

### Memory Module Benchmarks

| Benchmark | What it measures |
|-----------|------------------|
| **Belief revision accuracy** | Does model update correctly when evidence changes? |
| **Consistency** | Does model contradict prior statements? |
| **Grounding rate** | % of claims traceable to evidence |
| **Calibration** | Correlation between stated confidence and evidence quality |

### Validation Flow

1. Synthetic benchmarks first (controlled scenarios)
2. Open-weights integration (Llama/Mistral) with public evals
3. Publish results for credibility
4. Real-world metrics from deployed customers (opt-in)

Note: Belief revision benchmark does not exist publicly - creating one is a thought leadership opportunity.

---

## Research Context

### Problems This Solves

| Frontier Problem | Heat Model | Memory Module |
|------------------|------------|---------------|
| Context prioritization ("lost in the middle") | Direct fit | - |
| Long-horizon agent memory | Supports | Direct fit |
| Belief revision without retraining | - | Direct fit |
| Grounding/hallucination | Indirect | Direct fit |
| Attention efficiency | Direct fit | - |

### Related Work

- **DeepSeek Engram:** O(1) static memory lookup - we do dynamic
- **Titans:** Learned memory prioritizing by "surprise" - complementary, could use our heat as priors
- **HINDSIGHT:** Unifies factual recall with preference reasoning - we modularize for easier integration
- **Continuum Memory Architectures:** Alternatives to RAG - different approach, similar problem space

### Engrammic's Unique Value

- Explicit belief revision tracking (supersession chains)
- Epistemic provenance (no one else models this)
- Dynamic vs static memory

---

## Future Exploration: Alignment Research Tooling

**Paused pending validation interviews.**

Potential direction: Model Behavior Observatory - instrument models to log epistemic behavior, researchers query patterns (hallucination, consistency, calibration).

Interview targets: Anthropic alignment team, Redwood Research, ARC, Berkeley CHAI, MIT.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Frontier labs build it themselves | Open weights first strategy builds momentum before they react |
| Synthetic data doesn't match real patterns | Fine-tune with real data as it accumulates |
| No benchmark for belief revision | Create one - thought leadership opportunity |
| Integration friction with frontier labs | Start with adapter approach, lowest friction |
| Architecture shifts before memory module ships | Stay close to research, adapt design |

---

## Success Criteria

### Heat Model

- [ ] Prototype on synthetic data demonstrating >20% context efficiency gain
- [ ] Integration with Llama 3 or Mistral
- [ ] Published benchmark results
- [ ] First paying customer (enterprise or frontier)

### Memory Module

- [ ] Adapter prototype showing belief revision capability
- [ ] Reference integration with open-weights model
- [ ] Belief revision benchmark published
- [ ] Frontier lab partnership or acquisition interest
