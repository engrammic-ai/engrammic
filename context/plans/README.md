# Implementation Plans

Active implementation plans for context-service. Each plan lives in its own file named `<phase>-<description>.md`.

## Active plans

### v1.3 — EAG Surface Completion (current)
- [v1.3-master.md](./v1.3-master.md) — master plan for partner-demo readiness
- [v1.3-phase-0-flags.md](./v1.3-phase-0-flags.md) — feature flags (prerequisite)
- [v1.3a-pattern-detection.md](./v1.3a-pattern-detection.md) — co_occurrence, causal_chain, decay
- [v1.3b-llm-patterns.md](./v1.3b-llm-patterns.md) — LLM-detected patterns
- [v1.3c-session-compaction.md](./v1.3c-session-compaction.md) — `context_close_reasoning`, cross-chain
- [v1.3d-auto-reflection.md](./v1.3d-auto-reflection.md) — confidence/contradiction/uncertainty triggers
- [v1.3e-causal-completion.md](./v1.3e-causal-completion.md) — transitive invalidation, directionality, partial revision
- [v1.3g-ops-tooling.md](./v1.3g-ops-tooling.md) — tombstone asset, metrics

### v1.2 — Refinements + Protocol Migration (complete 2026-05-03)
- [v1.2-backlog.md](./v1.2-backlog.md) — summary. Most items archived, v1.2a carried to v1.3.
- [v1.2a-config-tuning.md](./v1.2a-config-tuning.md) — partial, v1.3 pre-req

### v1.1 — EAG Completion (complete 2026-05-03)
- Archived to `archive/v1.1-roadmap.md`

### v2 — Architecture Cleanup + REST API (current)
- [2026-05-02-v2-master.md](../docs/superpowers/plans/2026-05-02-v2-master.md) — master index. Four phases.
- [2026-05-02-v2-phase-1a-quick-wins.md](../docs/superpowers/plans/2026-05-02-v2-phase-1a-quick-wins.md) — settings consolidation + N+1 batching.
- [2026-05-02-v2-phase-1b-protocol.md](../docs/superpowers/plans/2026-05-02-v2-phase-1b-protocol.md) — protocol adoption for services + custodian.
- [2026-05-02-v2-phase-1b-api-design.md](../docs/superpowers/plans/2026-05-02-v2-phase-1b-api-design.md) — OpenAPI spec + REST contract docs.
- [2026-05-02-v2-phase-2-rest-api.md](../docs/superpowers/plans/2026-05-02-v2-phase-2-rest-api.md) — REST API implementation.
- Design spec: [2026-05-02-arch-cleanup-perf-rest-api.md](../docs/superpowers/specs/2026-05-02-arch-cleanup-perf-rest-api.md)

### v1-β — production hardening + paradigm completion (complete 2026-05-02)
- [v1-beta-master.md](./v1-beta-master.md) — master index. Six phases.
- [v1b-auth-finish.md](./v1b-auth-finish.md) — phase β1. Per-request MCP auth + silo ownership enforcement + WorkOS SDK verify.
- [v1b-dagster.md](./v1b-dagster.md) — phase β2 (sub-phased a/b/c). Asset migration: extraction → embedding+custodian → clustering+scheduling.
- [v1b-splade.md](./v1b-splade.md) — phase β3. SPLADE sparse retrieval + Qdrant hybrid search + RRF fusion.
- [v1b-silo-portability.md](./v1b-silo-portability.md) — phase β4. Silo export/import via JSONL with manifest + schema versioning.
- [v1b-integration-test-pack.md](./v1b-integration-test-pack.md) — phase β5. E2E ingest→query, cross-silo isolation, auth flow, failure-mode tests.
- [v1b-eag-completion.md](./v1b-eag-completion.md) — phase β6. Wire supersession + confidence primitives, schedule fact_promotion, hygiene cleanup.
- [v1b-architecture-cleanup.md](./v1b-architecture-cleanup.md) — phase β6+ (parallel). Storage protocol adoption (NF-003/006/009) + Settings consolidation (B2). Deferred from β0 review-cleanup.
- [v1b-review-cleanup.md](./v1b-review-cleanup.md) — phase β0. Orphan findings from the 2026-04-28 codebase review not owned by another β phase.

### v1-d — signals enhancement (active)
- [v1d-signals-enhancement.md](./v1d-signals-enhancement.md) — query-time heat ranking, unified decay model, write-side access events. Four phases behind feature flags.
- Spec: [signals-port.md](../specs/signals-port.md) (v1d section at bottom)

### v1-c — signals port (complete 2026-05-02)
- [v1c-signals-port.md](./archive/v1c-signals-port.md) — heat scoring (Dagster asset), freshness (query ranking), priority (custodian), access events (MCP reads). Fully wired.

### v1-α — close paradigm gaps (complete 2026-04-28)
- [v1a-claim-fact-promotion.md](./v1a-claim-fact-promotion.md) — wire `:Claim` → `:Fact` promotion via `primitives.eag.epistemology`; keep `:Finding` semantics intact.
- [v1a-edge-migration.md](./v1a-edge-migration.md) — migrate legacy `BELONGS_TO` edges to `MEMBER_OF`; drop dual-read; close stale audit TODOs.
- [v1a-validator-phase-b-finish.md](./v1a-validator-phase-b-finish.md) — split rejection metric into three counters; consolidate quality score in `BusinessRuleValidator`.
- [v1a-auth-toggle.md](./v1a-auth-toggle.md) — wire WorkOS auth behind an `AUTH_ENABLED` toggle; dev bypass with prod-guard.

### Spikes / evaluation
- [clustering-algo-eval.md](./clustering-algo-eval.md) — evaluate LPA / Louvain / HDBSCAN as replacements for Leiden; goal is incremental runs and dropping the igraph dependency.

### Background / design
- [eag-integration-audit.md](./eag-integration-audit.md) — port-day audit; some TODOs are addressed by v1-α plans above.
- [validator-refactor.md](./validator-refactor.md) — full 4-phase design; Phase A+B finishing in v1-α, C+D deferred.
- [meta-memory-roadmap.md](./meta-memory-roadmap.md) — phases 1–3 effectively shipped via `context_provenance`/`context_history`; phase 4 (reflection storage model) still notional.

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria
