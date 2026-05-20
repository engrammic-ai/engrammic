# Complink Technical FAQ

**Date:** 2026-05-20
**Context:** Follow-up questions from Complink meeting

---

## 1. How do you prevent context rot?

Context rot (stale or outdated information polluting retrieval) is addressed at multiple layers:

### Temporal validity
Every node has `valid_from` and `valid_to` timestamps. Queries filter by temporal window by default. Old context is still accessible for audit/history but doesn't pollute active retrieval.

### Heat and freshness signals
Nodes carry heat scores based on:
- **Recency** - when was it last accessed or updated
- **Frequency** - how often is it retrieved
- **Priority** - explicit importance weighting

Retrieval naturally ranks fresh, frequently-used context higher. Cold context deprioritizes without manual cleanup.

### Supersession
When context is updated, the new version explicitly supersedes the old via a graph edge. The superseded node:
- Remains in storage (audit trail, time-travel)
- Gets filtered from active queries
- Can be restored if the supersession was wrong

### Custodian synthesis
Background pipeline that:
- Detects contradictions between nodes
- Flags stale evidence (dead links, outdated citations)
- Proposes belief updates when underlying facts change
- Consolidates redundant context

### Evidence requirements
Knowledge-layer nodes require citations. If the evidence source becomes unavailable or contradicted, the system flags it for review rather than silently serving stale claims.

**Bottom line:** Context doesn't rot silently. The system actively manages freshness through signals, supersession, and synthesis. This is a key differentiator from stateless retrieval systems.

---

## 2. Data export

### Current state
No unified export endpoint yet. Underlying storage supports standard exports:
- **Graph (Memgraph):** Cypher EXPORT or DUMP commands
- **Vectors (Qdrant):** Snapshot API
- **Audit logs (Postgres):** pg_dump

### Planned
Unified export endpoint for enterprise customers:
- JSONL dump of all nodes + edges for a silo
- Scheduled backup to cloud storage (S3/GCS)
- Compliance-friendly format with full provenance

**Estimate:** 1-2 days to build if this is a requirement for Complink.

---

## 3. Multi-tenant silo architecture

### Current model
`silo_id` partitions all storage (graph, vectors, cache). One silo per tenant organization. Complete isolation at the storage layer.

### Complink deployment options

#### Option A: Complink internal only
```
complink (silo)
  - All Complink agents share context
  - Simple, single-tenant deployment
```

#### Option B: Platform multi-tenant
```
complink (silo)           - Complink's internal operations
customer-acme (silo)      - ACME Construction's context
customer-buildco (silo)   - BuildCo's context
customer-summit (silo)    - Summit Builders' context
...
```

Each construction company customer gets their own silo. Complete isolation. Complink as platform operator has admin read access across silos for support and analytics.

#### Option C: Federated domain knowledge (recommended for Complink)
```
complink-domain (silo)    - Shared construction domain knowledge
                            - Permitting workflows by jurisdiction
                            - Material specifications
                            - Contractor patterns
                            - Regulatory requirements
                            [Write: Complink only]
                            [Read: All customers]

customer-acme (silo)      - ACME's proprietary context
customer-buildco (silo)   - BuildCo's proprietary context
...
```

Benefits:
- Complink accumulates domain expertise over time
- All customers benefit from shared knowledge without data leakage
- Proprietary customer context stays isolated
- Complink's IP (domain knowledge) has clear ownership

### What needs implementation for Option C

| Feature | Status | Effort |
|---------|--------|--------|
| Multi-silo isolation | Done | - |
| Admin cross-silo read | Needs wiring | 2 days |
| Federated query (customer + domain) | Documented, not built | 0.5 day |
| Write isolation (domain silo read-only for customers) | Needs policy layer | 2 days |

**Implementation approach:** Add `linked_silos` field to silo config. Service layer fans out queries to `[silo_id, ...linked_silos]`, merges results. Expose via Admin API for platform operators to manage.

**Status:** Documented pattern. Build when customer commits.

---

## 4. Self-hosting and pricing

### SaaS tiers

| Tier | Price | Writes/mo | Recalls/mo | Profile |
|------|-------|-----------|------------|---------|
| Starter | $29/mo | 50,000 | 5,000 | standard |
| Pro | $129/mo | 300,000 | 30,000 | reasoning |
| Enterprise | Custom | Unlimited | Unlimited | all |

### Self-hosting options

#### Hybrid (recommended for most)
- Complink runs: Memgraph, Qdrant, Redis on their infra
- Engrammic runs: Synthesis pipeline, LLM orchestration
- Cost: ~$200/mo GPU (Hetzner) + platform fee

#### Fully on-premises
- Complink runs: Everything
- Engrammic provides: Docker images, Helm charts, support
- License: Annual subscription (not perpetual)

### Licensing model
- **Memgraph Community:** Free, no license fee
- **Engrammic platform:** Subscription-based
- **No per-seat charges**
- **No token metering** (flat rate at tier)

### Enterprise estimate for Complink

Given Complink's position as a platform serving multiple construction companies:

| Component | Estimate |
|-----------|----------|
| Platform fee (self-hosted) | $1,500-2,500/mo |
| SLA + priority support | +$500/mo |
| Their infra (Memgraph VM, Qdrant, GPU) | ~$400-600/mo |
| **Total** | **$2,400-3,600/mo** |

For SaaS deployment: $2,000-4,000/mo depending on volume, includes infra.

### No DRM
- Standard container deployment
- No license server or phone-home requirements
- Compliance-friendly for air-gapped environments

---

## 5. Silo economics

### Per-customer overhead
Each customer silo adds minimal overhead:
- Graph: Partition key, no separate instance
- Vectors: Namespace within collection, no separate cluster
- Cache: Key prefix, shared Redis

Marginal cost per customer silo: ~$0.50-2/mo (storage only).

### Scaling model
Complink pays based on total platform usage, not per-customer-silo count. This aligns incentives: they can onboard unlimited construction companies without per-seat anxiety.

### Domain silo value
The `complink-domain` silo is where Complink's IP accumulates. Over time:
- Curated construction knowledge base
- Regulatory/permitting expertise by jurisdiction  
- Material and contractor patterns
- Industry best practices

This becomes a moat. Competitors would need years to build equivalent domain context.

---

## Next steps

1. Confirm deployment preference (SaaS vs hybrid vs on-prem)
2. Confirm silo architecture (Option B vs C)
3. Scope data export requirements (formats, frequency, destination)
4. Draft enterprise agreement
