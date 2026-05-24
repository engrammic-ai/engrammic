# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-05-23)

**Shipped:**
- v2.22 Rate Limiting (tiered rate limiting for MCP tools and REST routes)
- v2.21 Beacon Telemetry Pipeline (Metabase dashboards, replaces Cloud Trace)
- v2.20 Documentation Site (docs.engrammic.ai)
- v2.19 Closed Beta Deployment (Cloud SQL, StatefulHost, CI/CD, DNS)
- v2.18 MCP OAuth + Middleware (OAuth flow for Cursor/Claude Code, FastMCP error/logging/timing middleware, 20+ client allowlist)
- v2.17 Wire Unpopulated Fields (optional schema fields in recall responses)
- v2.16 MCP Connection Stability (error boundaries + Direct VPC Egress)
- v2.15 Supersession Head Pointer (O(1) chain lookups via tail_id/head_id pointers)
- v2.14 Recall Optimization Phase 4 (similarity cache for semantic near-matches)
- v2.13 Recall Optimization Phase 3 (Qdrant scalar quantization, Matryoshka 512-dim validation)
- v2.12 Recall Optimization Phase 2 (tiered result cache, version-based invalidation, bypass_cache/max_age_seconds params)
- v2.11 Recall Optimization Phase 1 (embedding cache + TEI backend, 500ms -> 50ms)
- v2.10 GCP Deployment (Pulumi infra, Cloud Run API, GCE stateful host)
- v2.9 Review Followup (P0 security/reliability fixes, N+1 batching, LLM timeout/retry)
- v2.8 Content-Hash Dedup (full SHA256 hashes, dedup index, claim dedup tests)
- v2.7 MCP Tool Surface Redesign (intent-based tools with YAML config and profiles)
- v2.6 Semantic Reranking (Vertex AI reranking + LLM query expansion for entailment)
- v2.5 SAGE Job Consolidation (replaced 8 sensors with 3 scheduled jobs, pending work queries)
- v2.4 Heat Diffusion (Dagster asset, edge heat propagation, prewarm sweep)
- Self-Hosted Telemetry (two-tier beacon system, install ID, collector, docs)
- v2.3 Telemetry Expansion (OTEL metrics for all storage backends, LLM tokens, chain reuse)
- v2.2 Reasoning Chain Applicability (three-layer matching, DTW, implicit feedback)
- v2.1 Custodian Identity Split (4 identities with full LLM wiring + Dagster jobs/sensors)
- v2 Architecture Fixes (error envelopes, outbox pattern, raw Cypher mixin, hydration registry, ProposedBelief flow)
- v1.7 Auto-Tagging (tag config, cosine matching, Dagster pipelines)
- v1.6 Hybrid Storage (Postgres+Memgraph saga, consolidation, crystallization, GC)
- v1.5 Agent Identity (agent nodes, reflection filtering, chain continuity, per-silo config)
- v1.4.1 MCP QoL (consolidated to 10 tools: store, recall, link, admin, belief_state, update_belief, crystallize, accept_belief, reject_belief, skills)
- v1d Signals Enhancement (heat ranking, unified decay, write events)
- OSS Adoption Helpers (manifesto, quickstart READMEs for primitives/engine/mcp-client)
- MCP Client Scaffold (engrammic-mcp repo shipped)
- Pipeline Validation (heat, extraction, pattern detection validated)

## Active plans

| Plan | Description | Status |
|------|-------------|--------|
| [2026-05-20-self-hosted-rest-api-phase1.md](./2026-05-20-self-hosted-rest-api-phase1.md) | Self-hosted REST API: auth + Memory/Knowledge endpoints | Ready to execute |

## Future work

Specced or checkpointed for later implementation:

| Item | Spec/Note | Trigger |
|------|-----------|---------|
| **ML Products for Frontier Labs** | [ml-products-frontier-labs-design.md](../../docs/superpowers/specs/2026-05-23-ml-products-frontier-labs-design.md) | Post-fundraise; requires data capture instrumentation first |
| **Self-Hosted REST API Phase 2+** | [self-hosted-rest-api-design.md](../../docs/superpowers/specs/2026-05-20-self-hosted-rest-api-design.md) | After Phase 1 ships; Wisdom/Intelligence/Graph/Admin endpoints |
| **Concepts** | [concepts-design.md](../../docs/superpowers/specs/2026-05-18-concepts-design.md) | Post-closed-beta, when retrieval quality degrades at scale |

**ML Products for Frontier Labs:** Two products: Heat Model (context prioritization, TGNN) and Memory Module (epistemic reasoning, adapter/LoRA). Strategy is open weights first (Llama/Mistral), build momentum, then frontier labs adopt/acquire/partner. Requires data capture instrumentation in context-service before training can begin.

**Self-Hosted REST API:** Layer-aligned REST surface for self-hosted deployments. Phase 1 covers auth (proxy/JWT/API key) + Memory/Knowledge. Phase 2+ covers Wisdom, Intelligence, Graph, Search, Admin API.

**Concepts:** Emergent abstract nodes (Wisdom layer) that organize knowledge without asserting conclusions. Includes Weaver SAGE persona, weighted edges, 5-phase incremental impl plan.

## Spikes / drafts

| Plan | Status | Description |
|------|--------|-------------|
| [2026-05-18-gcp-deployment-improvements.md](./2026-05-18-gcp-deployment-improvements.md) | Draft | Distroless images, vuln scanning, health checks |
| [2026-05-18-context-checkpoint-hooks.md](./2026-05-18-context-checkpoint-hooks.md) | Spike | Claude Code hooks for context checkpoint/restore via Engrammic |
| [clustering-algo-eval.md](./clustering-algo-eval.md) | Spike | Evaluate LPA/HDBSCAN as Leiden replacements |
| [dagger-test-pipeline.md](./dagger-test-pipeline.md) | Draft | Dagger-based test pipeline |

## OSS track

| Plan | Description |
|------|-------------|
| [oss-master.md](./oss-master.md) | Master plan for open-source launch |
| [oss-engine.md](./oss-engine.md) | W1: Engine repo (single-tenant SQLite) |
| [oss-launch-prep.md](./oss-launch-prep.md) | W3: Repo hygiene + landing page |

## Reference

| Plan | Description |
|------|-------------|
| [eag-integration-audit.md](./eag-integration-audit.md) | Deferred items from EAG port |
| [../specs/reasoning-chain-applicability.md](../specs/reasoning-chain-applicability.md) | Spec: reasoning chain applicability matching design |
| [../specs/semantic-reranking.md](../specs/semantic-reranking.md) | Spec: semantic reranking with query expansion for entailment |

## Archive

Completed plans in `archive/`:
- Rate Limiting (2026-05-23) - tiered rate limiting for MCP tools and REST routes
- Beacon Telemetry Pipeline (2026-05-23) - Metabase dashboards, replaces Cloud Trace
- Documentation Site (2026-05-22) - docs.engrammic.ai
- Closed Beta Deployment (2026-05-22) - Cloud SQL, StatefulHost, CI/CD, DNS
- Data Lifecycle Management (2026-05-20) - forget tool, GDPR erasure, chain pruning
- MCP OAuth + Middleware (2026-05-20) - OAuth flow, FastMCP middleware, client allowlist
- Wire Unpopulated Fields (2026-05-19) - optional schema fields in recall responses
- MCP Connection Stability (2026-05-19) - error boundaries + Direct VPC Egress
- Supersession Head Pointer (2026-05-19) - O(1) chain lookups via tail_id/head_id pointers
- Recall Optimization Phase 4 (2026-05-19) - similarity cache for semantic near-matches
- Recall Optimization Phase 3 (2026-05-19) - Qdrant scalar quantization, Matryoshka validation
- Recall Optimization Phase 2 (2026-05-19) - tiered result cache, version-based invalidation
- Recall Optimization Phase 1 (2026-05-19) - embedding cache + TEI backend
- Source Tier Classification (2026-05-19) - source tier resolution for confidence scoring
- Epistemic Layer Fixes (2026-05-17) - belief architecture, flow compliance, evidence discipline
- Architectural Decisions (2026-05-16) - 9 decisions on enforcement, reliability, integration
- Cognitive Runtime Pivot (2026-05-07) - deferred pivot notes
- Partner Deployment (2026-05-08) - partner deployment planning
- Proposal Worker (2026-05-07) - proposal worker design
- Search Quality Document Expansion (2026-05-07) - query expansion spike
- ICP Skill Presets (2026-05-17) - per-silo preset binding, patterns delivery
- Identity LLM Wiring (2026-05-17) - Custodian LLM agents, Dagster jobs
- Architecture Review (2026-05-17) - hypergraph, consistency, custodian split decisions
- Unused Params Audit (2026-05-17) - codebase cleanup
- GCP Deployment (2026-05-16) - Pulumi infra, Cloud Run API, GCE stateful host
- Review Followup (2026-05-16) - P0 security/reliability fixes, N+1 batching, LLM timeout/retry
- Content-Hash Dedup (2026-05-16) - full SHA256 hashes, dedup index, claim dedup tests
- MCP Tool Surface Redesign (2026-05-16) - intent-based tools with YAML config and profiles
- Semantic Reranking (2026-05-16) - Vertex AI reranking + LLM query expansion
- SAGE Job Consolidation (2026-05-15) - 3 scheduled jobs replacing 8 sensors, pending work queries
- Heat Diffusion (2026-05-15) - Dagster asset, edge heat propagation, prewarm sweep
- Self-Hosted Telemetry (2026-05-13) - two-tier beacon, install ID, collector
- Telemetry Expansion (2026-05-13) - OTEL metrics for storage backends, LLM tokens
- Reasoning Chain Applicability (2026-05-12) - three-layer matching, DTW, implicit feedback
- Custodian Identity Split (2026-05-12) - 4 identities with LLM wiring + Dagster jobs
- OSS Adoption Helpers (2026-05-11)
- Pipeline Validation (2026-05-10)
- MCP Client Scaffold (2026-05-06)
- OSS Manifesto (2026-05-11)
- v2 Architecture Fixes (2026-05-07)
- E2E test scenarios (2026-05-06)
- as_of time-travel for node_ids (2026-05-06)
- v1.7 Auto-Tagging
- v1.6 Hybrid Storage
- v1.5 Agent Identity (5.0-5d)
- v1.4.1 MCP QoL
- v1d Signals Enhancement
- v1.3, v1.2, v1.1 EAG completion
- v1-beta production hardening
- v1-alpha paradigm gaps

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria
