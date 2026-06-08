# Engrammic Per-User Profit Margins

**Date:** 2026-05-20  
**Scenario:** API-Only (Gemini 2.5 Flash Batch)

---

## Per-User Profit Summary

Assuming users hit **tier limits** (worst case):

| Tier | Price | Your Cost | Profit/User | Margin |
|------|-------|-----------|-------------|--------|
| **Free** | $0 | $2.25 | -$2.25 | N/A (loss leader) |
| **Starter** | $29 | $5.24 | +$23.76 | **82%** |
| **Pro** | $129 | $17.43 | +$111.57 | **86%** |

---

## Starter Tier Breakdown ($29/mo)

**Included:** 50K writes + 5K recalls + 1GB storage

| Component | Calculation | Cost |
|-----------|-------------|------|
| Embeddings | 50K writes x $0.000007 | $0.35 |
| LLM - Recalls | 5K x $0.00028 (batch) | $1.40 |
| LLM - Synthesis | 500 jobs x $0.000975 | $0.49 |
| Infra share | $200/mo / 100 users | $2.00 |
| Storage | 1GB | $1.00 |
| **Total Cost** | | **$5.24** |
| **Revenue** | | **$29.00** |
| **Profit** | | **$23.76** |
| **Margin** | | **82%** |

---

## Pro Tier Breakdown ($129/mo)

**Included:** 300K writes + 30K recalls + 10GB storage

| Component | Calculation | Cost |
|-----------|-------------|------|
| Embeddings | 300K writes x $0.000007 | $2.10 |
| LLM - Recalls | 30K x $0.00028 (batch) | $8.40 |
| LLM - Synthesis | 3K jobs x $0.000975 | $2.93 |
| Infra share | $200/mo / 100 users | $2.00 |
| Storage | 10GB | $2.00 |
| **Total Cost** | | **$17.43** |
| **Revenue** | | **$129.00** |
| **Profit** | | **$111.57** |
| **Margin** | | **86%** |

---

## Free Tier Cost ($0/mo)

**Included:** 2K writes + 200 recalls + 50MB storage

| Component | Calculation | Cost |
|-----------|-------------|------|
| Embeddings | 2K writes x $0.000007 | $0.014 |
| LLM - Recalls | 200 x $0.00028 | $0.056 |
| LLM - Synthesis | 20 jobs x $0.000975 | $0.02 |
| Infra share | $200/mo / 100 users | $2.00 |
| Storage | 50MB | $0.16 |
| **Total Cost** | | **$2.25** |
| **Revenue** | | **$0.00** |
| **Loss** | | **-$2.25** |

---

## Realistic Margins (Average Usage)

Most users use 30-50% of tier limits:

| Tier | At Max (100%) | At 40% Usage | At 20% Usage |
|------|---------------|--------------|--------------|
| Starter | 82% | **92%** | **95%** |
| Pro | 86% | **94%** | **96%** |

---

## Overage Profit Margins

| Resource | Overage Price | Your Cost | Profit/Unit | Margin |
|----------|---------------|-----------|-------------|--------|
| Writes | $0.50/1K | $0.007 | $0.493 | **99%** |
| Recalls | $2.00/1K | $0.28 | $1.72 | **86%** |
| Storage | $5.00/GB | $0.50 | $4.50 | **90%** |

---

## Break-Even Analysis

**Fixed Infrastructure Cost:** $200/mo

| Metric | Value |
|--------|-------|
| Starter users to cover infra | ~9 users |
| Pro users to cover infra | ~2 users |
| Free users supportable per Starter | ~10 free per 1 paid |
| Free users supportable per Pro | ~50 free per 1 paid |

---

## Revenue Projections

| User Mix | MRR | ARR | Monthly Profit |
|----------|-----|-----|----------------|
| 50 Starter | $1,450 | $17,400 | $1,188 |
| 100 Starter | $2,900 | $34,800 | $2,376 |
| 50 Starter + 20 Pro | $4,030 | $48,360 | $3,419 |
| 100 Starter + 50 Pro | $9,350 | $112,200 | $7,955 |
| 200 Starter + 100 Pro | $18,700 | $224,400 | $15,909 |

**Assumptions:** 100 user base for infra share, users at 40% average usage

---

## Key Takeaways

1. **Margins are healthy** - 82-86% at max usage, 92-96% at realistic usage
2. **Pro tier is most profitable** - $111/user profit vs $24/user on Starter
3. **Free tier is cheap** - Only $2.25/user loss, sustainable as acquisition channel
4. **Overages are gold** - 86-99% margin on usage beyond tier limits
5. **Break-even is low** - Just 9 Starter or 2 Pro users covers all fixed costs
