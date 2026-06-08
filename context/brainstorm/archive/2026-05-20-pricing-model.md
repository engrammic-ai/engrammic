# Engrammic Pricing Model Analysis

**Date:** 2026-05-20  
**Status:** Draft for review

---

## 1. Cost Basis

### 1.1 LLM API Pricing (Sources: Official Provider Docs)

| Provider | Model | Input/1M | Output/1M | Source |
|----------|-------|----------|-----------|--------|
| Google | Gemini 2.5 Flash | $0.30 | $2.50 | [Vertex AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| Google | Gemini 2.5 Flash (Batch) | $0.15 | $1.25 | [Vertex AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| Google | Gemini 3.1 Pro | $2.00 | $12.00 | [Vertex AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| Google | Gemini 2.5 Flash-Lite | $0.10 | $0.40 | [Vertex AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) |
| OpenAI | text-embedding-3-small | $0.02 | N/A | [OpenAI Pricing](https://openai.com/api/pricing/) |
| Anthropic | Claude Haiku 4.5 | $1.00 | $5.00 | [Anthropic Pricing](https://www.anthropic.com/pricing) |
| Anthropic | Claude Sonnet 4.6 | $3.00 | $15.00 | [Anthropic Pricing](https://www.anthropic.com/pricing) |

### 1.2 Infrastructure Pricing (Sources: Provider Docs)

| Component | Provider | Spec | Monthly Cost | Source |
|-----------|----------|------|--------------|--------|
| Vector DB | Qdrant Cloud | 2GB cluster | $30-60 | [Qdrant Pricing](https://qdrant.tech/pricing/) |
| Graph DB | Memgraph | Self-hosted Community (license) | $0 | [Memgraph Pricing](https://memgraph.com/pricing) |
| Graph DB VM | GCP | n2-standard-4 (Memgraph host) | $120 | [GCP Compute Pricing](https://cloud.google.com/compute/vm-instance-pricing) |
| Cache | Upstash | Serverless Redis | $10-25 | [Upstash Pricing](https://upstash.com/pricing) |
| Compute | Cloud Run | API hosting | $20-50 | [Cloud Run Pricing](https://cloud.google.com/run/pricing) |
| **Total Base Infra** | | | **$180-255** | |

### 1.3 Self-Hosted GPU Options (Sources: Provider Sites)

| Provider | GPU | VRAM | Hourly | Monthly (24/7) | Source |
|----------|-----|------|--------|----------------|--------|
| Hetzner | RTX 4000 Ada (GEX44) | 20GB | N/A | EUR 184 (~$200) | [Hetzner](https://www.hetzner.com/dedicated-rootserver/gex44/) |
| Hetzner | RTX 6000 Ada (GEX130) | 48GB | N/A | EUR 838 (~$910) | [Hetzner](https://www.hetzner.com/dedicated-rootserver/gex130/) |
| Vast.ai | A100 80GB | 80GB | $0.60-1.07 | $430-770 | [Vast.ai](https://vast.ai/pricing) |
| Vast.ai | H100 80GB | 80GB | $0.90-1.50 | $650-1,100 | [Vast.ai](https://vast.ai/pricing) |
| RunPod | A100 80GB | 80GB | $0.79 | $570 | [RunPod](https://www.runpod.io/pricing) |
| RunPod | RTX 4090 | 24GB | $0.44 | $320 | [RunPod](https://www.runpod.io/pricing) |

---

## 2. Per-Operation Cost Analysis

### 2.1 Token Estimates per Operation

| Operation | Input Tokens | Output Tokens | Embedding Tokens | Notes |
|-----------|--------------|---------------|------------------|-------|
| remember | 0 | 0 | 300 | Embedding only |
| learn | 0 | 0 | 400 | Embedding only (larger with evidence) |
| believe | 0 | 0 | 0 | Graph write only |
| recall (search) | 600 | 150 | 100 | Query embed + reranking LLM |
| recall (by ID) | 0 | 0 | 0 | Graph read only |
| trace | 0 | 0 | 0 | Graph traversal only |
| link | 0 | 0 | 0 | Graph write only |
| reason | 0 | 0 | 150 | Embedding for conclusion |
| reflect | 0 | 0 | 0 | Graph write only |
| hypothesize | 0 | 0 | 0 | Graph write only |
| revise | 0 | 0 | 0 | Graph update only |
| commit | 600 | 150 | 0 | Validator LLM (if enabled) |
| synthesis (sage.synthesizer) | 1500 | 600 | 0 | Background batch job |

### 2.2 Cost per Operation (Gemini 2.5 Flash Standard)

| Operation | Embedding Cost | LLM Input Cost | LLM Output Cost | Total Cost/Op |
|-----------|----------------|----------------|-----------------|---------------|
| remember | $0.000006 | $0 | $0 | **$0.000006** |
| learn | $0.000008 | $0 | $0 | **$0.000008** |
| believe | $0 | $0 | $0 | **$0.000001** |
| recall (search) | $0.000002 | $0.00018 | $0.000375 | **$0.000557** |
| recall (by ID) | $0 | $0 | $0 | **$0.000001** |
| trace | $0 | $0 | $0 | **$0.000001** |
| link | $0 | $0 | $0 | **$0.000001** |
| reason | $0.000003 | $0 | $0 | **$0.000003** |
| reflect | $0 | $0 | $0 | **$0.000001** |
| hypothesize | $0 | $0 | $0 | **$0.000001** |
| revise | $0 | $0 | $0 | **$0.000001** |
| commit (w/ validator) | $0 | $0.00018 | $0.000375 | **$0.000555** |
| synthesis | $0 | $0.00045 | $0.0015 | **$0.00195** |

### 2.3 Cost per Operation (Gemini 2.5 Flash Batch - 50% off)

| Operation | Total Cost/Op | vs Standard |
|-----------|---------------|-------------|
| remember | **$0.000006** | same (embedding) |
| learn | **$0.000008** | same (embedding) |
| recall (search) | **$0.000280** | 50% savings |
| commit (w/ validator) | **$0.000278** | 50% savings |
| synthesis | **$0.000975** | 50% savings |

### 2.4 Cost per Operation (Gemini 3.1 Pro - Premium Quality)

| Operation | Total Cost/Op | vs Flash |
|-----------|---------------|----------|
| recall (search) | **$0.003** | 5x more |
| commit (w/ validator) | **$0.003** | 5x more |
| synthesis | **$0.0102** | 5x more |

---

## 3. Blended Cost per User

### 3.1 Assumptions

- Average user: 70% writes (remember/learn), 25% recalls (search), 5% other
- Synthesis runs 1x per 100 writes (SAGE batch)
- 20% of recalls use reranking
- 10% of commits use validator

### 3.2 Cost per 1,000 Operations (Blended)

| Model Choice | Write Ops (700) | Recall Ops (250) | Other (50) | Synthesis (10) | Total/1K Ops |
|--------------|-----------------|------------------|------------|----------------|--------------|
| Flash Standard | $0.0049 | $0.028 | $0.00005 | $0.0195 | **$0.052** |
| Flash Batch | $0.0049 | $0.014 | $0.00005 | $0.00975 | **$0.029** |
| Pro (premium) | $0.0049 | $0.15 | $0.00005 | $0.102 | **$0.257** |

### 3.3 Cost at Tier Limits

**Starter Tier (50K writes + 5K recalls):**

| Model | Write Cost | Recall Cost | Synthesis Cost | Infra Share | Total | @ $29 Price | Margin |
|-------|------------|-------------|----------------|-------------|-------|-------------|--------|
| Flash Standard | $0.35 | $2.79 | $0.98 | $1.00 | **$5.12** | $29 | **82%** |
| Flash Batch | $0.35 | $1.40 | $0.49 | $1.00 | **$3.24** | $29 | **89%** |

**Pro Tier (300K writes + 30K recalls):**

| Model | Write Cost | Recall Cost | Synthesis Cost | Infra Share | Total | @ $129 Price | Margin |
|-------|------------|-------------|----------------|-------------|-------|--------------|--------|
| Flash Standard | $2.10 | $16.71 | $5.85 | $2.00 | **$26.66** | $129 | **79%** |
| Flash Batch | $2.10 | $8.40 | $2.93 | $2.00 | **$15.43** | $129 | **88%** |

---

## 4. Competitor Pricing Comparison

| Provider | Free Tier | Entry Paid | Mid Tier | Enterprise | Source |
|----------|-----------|------------|----------|------------|--------|
| mem0 | 10K add + 1K retrieve | $19/mo (50K+5K) | **None** - jumps to $249 Pro | Custom | [mem0.ai/pricing](https://mem0.ai/pricing) |
| Zep | 1K credits | $25/mo (10K credits) | $75/mo (40K credits) | Custom | [getzep.com/pricing](https://getzep.com/pricing) |
| Langfuse | 50K units | $29/mo (100K units) | $199/mo | $2,499/mo | [langfuse.com/pricing](https://langfuse.com/pricing) |
| Pinecone | Free (2GB) | Usage-based serverless | $50/mo+ standard | $500/mo+ | [pinecone.io/pricing](https://pinecone.io/pricing) |

**Note:** mem0 has no mid-tier option. Their pricing jumps from $19 Starter directly to $249 Pro. This leaves a gap where Engrammic's $129 Pro tier has no direct competitor.

---

## 5. Proposed Pricing Tiers

### 5.1 Tier Structure

| Tier | Price | Writes/mo | Recalls/mo | Storage | Profile | Target User |
|------|-------|-----------|------------|---------|---------|-------------|
| **Free** | $0 | 2,000 | 200 | 50MB | standard | Evaluation, hobbyists |
| **Starter** | $29/mo | 50,000 | 5,000 | 1GB | standard | Indie devs, early startups |
| **Pro** | $129/mo | 300,000 | 30,000 | 10GB | reasoning | Growing teams, production |
| **Enterprise** | Custom | Unlimited | Unlimited | Unlimited | all | Scale + SLA + support |

### 5.2 Overage Pricing

| Resource | Overage Price | Our Cost | Margin |
|----------|---------------|----------|--------|
| Writes | $0.50 / 1,000 | ~$0.007 | **99%** |
| Recalls | $2.00 / 1,000 | ~$0.28 | **86%** |
| Storage | $5.00 / GB | ~$0.50 | **90%** |

### 5.3 Annual Discount

- 2 months free (17% off) for annual commitment
- Starter Annual: $290/year (vs $348)
- Pro Annual: $1,290/year (vs $1,548)

---

## 6. Margin Analysis by Scenario

### 6.1 Scenario A: API-Only (Gemini 2.5 Flash Batch)

**Fixed Costs:** $200/mo (infra including Memgraph VM)

| Metric | Starter | Pro |
|--------|---------|-----|
| Price | $29 | $129 |
| Variable Cost | $3.24 | $15.43 |
| Fixed Cost Share (100 users) | $2.00 | $2.00 |
| **Total Cost** | **$5.24** | **$17.43** |
| **Margin** | **82%** | **86%** |

### 6.2 Scenario B: Hybrid (Self-Host Embeddings + Reranking GPU)

**Fixed Costs:** $200 infra + $200 Hetzner GEX44 GPU = $400/mo

| Metric | Starter | Pro |
|--------|---------|-----|
| Price | $29 | $129 |
| Variable Cost (LLM only) | $1.47 | $8.78 |
| Fixed Cost Share (100 users) | $4.00 | $4.00 |
| **Total Cost** | **$5.47** | **$12.78** |
| **Margin** | **81%** | **90%** |

Break-even: ~20 paying users to cover fixed GPU cost

### 6.3 Scenario C: Fully Self-Hosted

**Fixed Costs:** $200 infra + $200 rerank GPU (GEX44) + $1,100 H100 (Vast.ai) = $1,500/mo

| Metric | Starter | Pro |
|--------|---------|-----|
| Price | $29 | $129 |
| Variable Cost | $0.40 | $2.40 |
| Fixed Cost Share (100 users) | $15.00 | $15.00 |
| **Total Cost** | **$15.40** | **$17.40** |
| **Margin** | **47%** | **87%** |

Break-even: ~55 paying users minimum; only profitable at scale

**Note:** Using GEX130 (RTX 6000 Ada, $910/mo) instead of GEX44 would increase fixed costs to $2,210/mo.

---

## 7. Unit Economics Summary

### 7.1 Key Metrics (Scenario A - Recommended)

| Metric | Value |
|--------|-------|
| CAC assumption | $50 (content marketing) |
| Starter LTV (12mo, 10% churn) | $261 |
| Pro LTV (12mo, 5% churn) | $1,394 |
| Starter LTV:CAC | 5.2x |
| Pro LTV:CAC | 27.9x |
| Gross Margin (blended) | 85-86% |
| Contribution Margin | ~80% |

### 7.2 Revenue Targets

| Users | MRR | ARR | Notes |
|-------|-----|-----|-------|
| 100 Starter | $2,900 | $34,800 | Seed stage |
| 50 Starter + 20 Pro | $4,030 | $48,360 | Series A path |
| 200 Starter + 50 Pro | $12,250 | $147,000 | Series A |
| 500 Starter + 100 Pro | $27,400 | $328,800 | Growth stage |

---

## 8. Recommendations

### 8.1 Launch Configuration

1. **Model:** Gemini 2.5 Flash (Batch API where possible)
2. **Infrastructure:** API-only (Scenario A)
3. **Tiers:** Free, Starter ($29), Pro ($129)
4. **Billing unit:** Writes + Recalls (10:1 ratio, like mem0)

### 8.2 Growth Triggers

| Trigger | Action |
|---------|--------|
| 100+ paying users | Add Hetzner GPU for embeddings/reranking |
| 500+ users OR 5B tokens/mo | Evaluate H100 for synthesis |
| Enterprise demand | Add Gemini Pro option as premium tier |

### 8.3 What NOT to Bill For

- Storage (cheap, include generously)
- Per-seat (industry norm is unlimited users)
- Graph operations (link, trace, believe - negligible cost)
- Skill profiles (patterns - free)

---

## Appendix: Data Sources

1. [Vertex AI Generative AI Pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing) - Gemini models
2. [OpenAI API Pricing](https://openai.com/api/pricing/) - Embeddings
3. [Anthropic Pricing](https://www.anthropic.com/pricing) - Claude models (reference)
4. [Qdrant Cloud Pricing](https://qdrant.tech/pricing/) - Vector DB
5. [Memgraph Pricing](https://memgraph.com/pricing) - Graph DB
6. [Upstash Pricing](https://upstash.com/pricing) - Redis
7. [Cloud Run Pricing](https://cloud.google.com/run/pricing) - Compute
8. [Hetzner GPU Servers](https://www.hetzner.com/dedicated-rootserver/) - Self-hosted GPU
9. [Vast.ai Pricing](https://vast.ai/pricing) - GPU cloud
10. [RunPod Pricing](https://www.runpod.io/pricing) - GPU cloud
11. [mem0.ai Pricing](https://mem0.ai/pricing) - Competitor
12. [Zep Pricing](https://getzep.com/pricing) - Competitor
13. [Langfuse Pricing](https://langfuse.com/pricing) - Competitor
14. [Pinecone Pricing](https://pinecone.io/pricing) - Competitor
