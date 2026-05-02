# API / Wholesale Pricing - Draft

**Date:** 2026-05-02
**Status:** Draft for partner conversations (Silt, etc.)
**Purpose:** Usage-based pricing for B2B partners integrating Delta Prime as infrastructure

## Why Wholesale Pricing

SaaS tiers work for end-customers. B2B partners need:
- Predictable unit economics for their margin model
- Usage-based costs that scale with their customers
- No per-seat constraints that don't map to their model

## Per-Operation Pricing

| Operation | Our cost | Wholesale price | Margin | Notes |
|-----------|----------|-----------------|--------|-------|
| **Store** (with extraction) | $0.0006 | $0.002 | 70% | Embedding + LLM extraction |
| **Store** (no extraction) | $0.00001 | $0.00005 | 80% | Embedding only |
| **Lookup** | $0.000002 | $0.00001 | 80% | Query embedding + search |
| **Extraction** (Custodian) | $0.005 | $0.015 | 70% | Deep extraction pass |

### Simplified for sales conversations

| Operation | Price |
|-----------|-------|
| Store | $2 per 1,000 |
| Lookup | $0.01 per 1,000 |
| Extraction | $15 per 1,000 |

## API Partner Tiers

Aggressive pricing to win first partners. Margin is thin but acceptable for volume + reference value.

| Tier | Monthly | Stores | Lookups | Extractions | Overage |
|------|---------|--------|---------|-------------|---------|
| **API Starter** | $49 | 50K | 500K | 5K | Standard rates |
| **API Growth** | $299 | 300K | 3M | 30K | 10% discount |
| **API Scale** | $999 | 1.5M | 15M | 150K | 20% discount |
| **API Enterprise** | Custom | Custom | Custom | Custom | Volume negotiated |

### Margin analysis (honest)

| Tier | Price | Typical cost | Margin | Notes |
|------|-------|--------------|--------|-------|
| API Starter | $49 | ~$30 | 39% | Thin but land |
| API Growth | $299 | ~$220 | 26% | Reference customer value |
| API Scale | $999 | ~$600 | 40% | Healthier at scale |

Trade-off: Low margin early = faster adoption. Acceptable because:
- First API partners = reference customers
- Volume commits cover fixed costs
- Expand on usage as they grow

### What's included at all tiers

- REST API access (primary for B2B)
- MCP server access (for their agents)
- Unlimited silos
- Standard SLA (99.5% uptime)
- Email support

### Enterprise add-ons

| Add-on | Price | Notes |
|--------|-------|-------|
| SSO (WorkOS) | $125/connection/mo | Per customer org |
| Dedicated instance | $500/mo | Isolated infra |
| Custom SLA (99.9%) | +20% | With credits |
| Audit log export | $50/mo | SIEM integration |
| Priority support | $200/mo | Slack channel + 4hr response |

## Partner Scenarios

### Scenario A: Silt (PM decision tracking)

**Profile:**
- 100 customer orgs on their platform
- Each org: ~2K contexts/mo (decisions from Slack/Linear/Notion)
- Each org: ~10K lookups/mo
- Moderate extraction (decisions need curation)

**Monthly usage:**
- Stores: 200K
- Lookups: 1M
- Extractions: 20K

**Cost at API Growth ($299/mo):**
- Included: 300K stores, 3M lookups, 30K extractions
- Usage: within limits
- **Total: $299/mo**

**Silt's unit economics:**
- If Silt charges $50/org/mo = $5,000 MRR
- Delta Prime cost = $299 = 6% of revenue
- **94% gross margin on memory infra**

This is the number that closes deals.

### Scenario B: CS Memory Platform

**Profile:**
- 50 customer orgs
- Each org: ~5K contexts/mo (account histories, promises)
- Each org: ~20K lookups/mo (agents querying constantly)
- Heavy extraction (structured claims from conversations)

**Monthly usage:**
- Stores: 250K
- Lookups: 1M
- Extractions: 50K

**Cost at API Growth ($299/mo):**
- Stores: 250K (under 300K limit)
- Lookups: 1M (under 3M limit)
- Extractions: 50K - 30K included = 20K overage at $0.0135 = $270

**Total: $569/mo**

### Scenario C: Heavy Enterprise

**Profile:**
- 500 customer orgs
- Heavy usage across all operations

**Monthly usage:**
- Stores: 2M
- Lookups: 20M
- Extractions: 200K

**Cost at API Scale ($999/mo):**
- Stores: 2M - 1.5M = 500K overage at $0.0016 = $800
- Lookups: 20M - 15M = 5M overage at $0.000008 = $40
- Extractions: 200K - 150K = 50K overage at $0.012 = $600

**Total: $2,439/mo**

At this scale, move to Enterprise with volume pricing.

## Comparison to SaaS Tiers

| Pricing model | Best for | Pros | Cons |
|---------------|----------|------|------|
| **SaaS tiers** | End customers, small teams | Simple, predictable | Doesn't scale for platforms |
| **API wholesale** | B2B partners, platforms | Unit economics clarity | More complex billing |

## Implementation Notes

### Billing infrastructure needed

- [ ] Usage metering per silo/org
- [ ] Monthly usage aggregation
- [ ] Overage calculation
- [ ] Invoice generation (Stripe usage-based billing)

### Rate limiting

| Tier | Requests/sec | Burst |
|------|--------------|-------|
| API Starter | 10 | 50 |
| API Growth | 50 | 200 |
| API Scale | 200 | 1000 |
| Enterprise | Custom | Custom |

### Monitoring for partners

- Usage dashboard (current period)
- Projected monthly cost
- Usage alerts (80%, 100% of included)
- Per-silo breakdown

## Open Questions

- [ ] Should extraction be opt-in per store, or always-on with lazy triggering?
- [ ] How to handle model tier selection (Groq 8B vs Flash vs Flash-Lite)?
- [ ] Annual commit discounts (15-20% typical)?
- [ ] Free trial for API partners (30 days? usage cap?)

## Changelog

- **2026-05-02** - Initial draft based on cost simulation and Silt partner conversation
