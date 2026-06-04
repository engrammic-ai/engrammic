# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-06-04)

**Recent:**
- v2.36 Self-Serve Org Provisioning - Auto-provision personal org for no-org signups (PR #55)
- v2.35 Multi-Format Skill Installation - Cursor .mdc and Gemini GEMINI.md formats
- v2.34 Harness-Agnostic Enforcement - Write-time affinity, tick() enhancement, session state
- v2.33 Codebase Audit Fixes - Orphan jobs, commitment label, mcp-client sync
- v2.32-v2.1 (see archive for full history)

## Active plans

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-04-heat-utilization-phase1.md](./2026-06-04-heat-utilization-phase1.md) ([design](./2026-06-04-heat-utilization-design.md)) | Brain path decay floor + tier-driven summaries for Somnus benchmark | Ready to execute |
| [2026-06-01-brain-architecture.md](./2026-06-01-brain-architecture.md) | Reactive brain architecture: 20 transactions, 8 invariants | Phases 2-7 complete, cutover blocked |
| [2026-06-03-brain-cutover-and-quality-fixes.md](./2026-06-03-brain-cutover-and-quality-fixes.md) | Wire MCP to brain transactions, coverage reporting | Blocked on invariant fixes |

## Pending (not started)

| Plan | Description | Status |
|------|-------------|--------|
| [2026-05-30-join-engrammic-onboarding-plan.md](./2026-05-30-join-engrammic-onboarding-plan.md) ([design](./2026-05-30-join-engrammic-onboarding-design.md)) | join.engrammic.ai onboarding app | Ready to execute |
| [2026-05-30-evidence-verification.md](./2026-05-30-evidence-verification.md) | Evidence verification via Nango | Ready to execute |
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
- Multi-Format Skill Installation (2026-05-28) - Cursor .mdc and Gemini GEMINI.md formats for installer CLI
- Harness-Agnostic Enforcement (2026-05-28) - write-time affinity, tick() enhancement, session state, nudges
- Codebase Audit Fixes (2026-05-28) - orphan jobs, commitment label, mcp-client sync, dead code cleanup
- Dagster Pipeline Deps Fix (2026-05-27) - add missing asset dependencies for SAGE pipelines
- Refresh Token Persistence (2026-05-26) - draft, deferred
- Context Checkpoint Hooks (2026-05-18) - spike, deferred
- GCP Deployment Improvements (2026-05-18) - draft, deferred
- PostgreSQL Telemetry (2026-05-27) - replace SigNoz/OTEL with PG tables, MetricsBuffer, Dagster jobs
- Self-Hosted Distribution Phase 2 (2026-05-26) - version deprecation warnings, /versions endpoint, quickstart docs
- Self-Hosted Distribution Phase 1 (2026-05-26) - license validation, Docker bundle, installer CLI
- Engagement Plan E (2026-05-26) - session ID config, engage hook, skill, AGENTS.md, docs
- Engagement Plan D (2026-05-25) - touch counter, soft-to-hard escalation, empty results on hard mode
- Engagement Plan C (2026-05-25) - engagement field in recall, dismiss/tick verbs
- Engagement Plan B (2026-05-25) - sage.validator, Contradiction/StaleCommitment markers, inline flagging, Redis index
- Telemetry & Observability (2026-05-25) - SigNoz infra, OTEL metrics (superseded by pg-telemetry)
- Verb Promotion Plan A (2026-05-25) - accept/reject promoted to agent-facing in reasoning profile
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
- OSS Engine (2026-05-28) - engine repo shipped v0.1.1, SQLite store, all MCP tools
- OSS Master (2026-05-28) - W1 shipped; W2/W3 deferred post-fundraise
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
