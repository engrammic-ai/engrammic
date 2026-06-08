# Hindsight / TEMPR Analysis

**Source:** Vectorize, MIT-licensed, Dec 2025
**Paper:** arxiv 2512.12818

## Architecture Overview

Hindsight uses TEMPR (retain/recall) + CARA (reflect) architecture.

### Four-Way Parallel Retrieval

All channels run simultaneously, then fuse results:

1. **Semantic (Vector):** HNSW-based pgvector, cosine similarity
2. **BM25 Keyword:** GIN indices, excels at proper nouns and exact terms where embeddings blur
3. **Graph (Spreading Activation):** Starts from semantic hits, propagates along edges with decay factors and link-type multipliers (causal > entity > temporal)
4. **Temporal:** Detects time constraints via hybrid parsing (rule-based + seq2seq fallback), filters by occurrence interval overlap, scores by proximity

### Reciprocal Rank Fusion (RRF)

```
score(memory) = sum over channels: 1/(k + rank_in_channel)
```

Where k=60. Advantages:
- No score calibration across heterogeneous systems
- Missing items handled gracefully (just omit contribution)
- Elevates memories consistently ranked across multiple strategies

### Post-Fusion

1. Cross-encoder reranking (ms-marco-MiniLM-L-6-v2)
2. Token budget filtering (greedy top-ranked until context limit)

### Memory Organization

Four networks (maps loosely to our layers):
- **World:** Objective facts (~ Knowledge)
- **Experience:** Agent biography (~ Memory)
- **Opinion:** Subjective beliefs with confidence (~ Wisdom)
- **Observation:** Entity summaries

### CARA Opinion Updates

Confidence scores strengthen/weaken on new evidence:
- Retrieves related opinions via entity overlap + semantic similarity
- Assesses evidence relationship: reinforce/weaken/contradict/neutral
- Updates confidence accordingly

## Benchmark Reality

**Claimed:** 91.4% on LongMemEval (highest published)

**Concerns:**
- Self-reported by Vectorize
- LongMemEval measures `recall_any@5` (was memory retrieved), not answer correctness
- Some vendors hand-tune to specific failed questions, re-test same items
- Independent audits found ~88-89% without API reranking

**Takeaway:** Benchmark methodology is sound (ICLR 2025), but vendor scores are directional, not gospel.

## Borrowable Patterns for Engrammic

### Immediate Wins

| Pattern | Current State | Improvement |
|---------|--------------|-------------|
| BM25 channel | Missing | Add for exact name/term matches |
| RRF fusion | Score-based fusion | Simpler, no calibration needed |
| Temporal filtering | Edges exist, unused in recall | Filter by occurrence overlap |

### Consider Later

- Spreading activation with decay factors (we have PPR, similar concept)
- Opinion confidence tracking (similar to belief architecture)
- Cross-encoder reranking (expensive, profile first)

## LongMemEval Harness Decision

**Use official harness** (github.com/xiaowu0162/LongMemEval-V2) instead of Somnus adapters.

- Harness at `evaluation/harness.py`, config-driven
- LLM-as-judge (GPT-4o, >97% human agreement)
- Write thin Engrammic adapter exposing `recall` as memory backend

**Why not Somnus:**
- `seed_with_supersession()` unimplemented
- Broken temporal metadata handling
- Custom ICP scenarios can wait; standard harness + honest methodology is better for credentialing
