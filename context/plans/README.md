# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-06-09)

**Focus:** Credible benchmark numbers via official LongMemEval-V2 harness (Somnus has harness issues)

**Recent:**
- v2.38 Embedding Batching Phase 1 - Vertex AI batch calls via `batched` library (complete)
- v2.37 Heat Utilization Phase 1 - Brain path decay floor + tier-driven summaries (complete)
- v2.36 Self-Serve Org Provisioning - Auto-provision personal org for no-org signups (PR #55)

## Active plans

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-09-longmemeval-v2-harness.md](./2026-06-09-longmemeval-v2-harness.md) | Official LongMemEval-V2 harness with Engrammic adapter | Ready |
| [2026-06-07-fix-recall-read-path.md](./2026-06-07-fix-recall-read-path.md) | Fix rerank score write-back + threshold, full content by default | Active |
| [recall-quality-improvement.md](./recall-quality-improvement.md) | Question-answer asymmetry research, query expansion | Draft |
| [polish-audit-2026-06-08.md](./polish-audit-2026-06-08.md) | 7 critical + high findings from codebase audit | Triage |

## Draft / design

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-08-rrf-fusion.md](./2026-06-08-rrf-fusion.md) | Cross-channel RRF fusion for recall (vector + graph) | Ready |
| [2026-06-08-wisdom-layer-split.md](./2026-06-08-wisdom-layer-split.md) | Separate Commitments (agent) from Beliefs (SAGE) | Draft |
| [2026-06-08-unified-recall-and-write-dedup.md](./2026-06-08-unified-recall-and-write-dedup.md) | Merge retrieval paths, add write-time semantic dedup | Draft |
| [2026-06-06-write-quality-gate.md](./2026-06-06-write-quality-gate.md) | Write-path quality enforcement with structural checks | Ready |
| [error-boundary-surface-invariants.md](./error-boundary-surface-invariants.md) | Error boundary design notes | Notes |

## Pending (not started)

| Plan | Description | Blocker |
|------|-------------|---------|
| [2026-06-05-rerank-optimization.md](./2026-06-05-rerank-optimization.md) | Semantic rerank cache (L1 exact, L2 similarity) | — |
| [2026-06-05-embedding-batching-phase2.md](./2026-06-05-embedding-batching-phase2.md) | Adaptive batching, queue depth tuning | Phase 1 complete |
| [2026-06-05-admin-dashboard.md](./2026-06-05-admin-dashboard.md) | Operator dashboard (memory state, usage, health) | REST API Phase 1 |
| [2026-06-04-supersession-chain-retrieval.md](./2026-06-04-supersession-chain-retrieval.md) | `history` MCP tool for supersession chains | — |
| [2026-05-30-join-engrammic-onboarding-plan.md](./2026-05-30-join-engrammic-onboarding-plan.md) ([design](./2026-05-30-join-engrammic-onboarding-design.md)) | join.engrammic.ai onboarding app | — |
| [2026-05-30-evidence-verification.md](./2026-05-30-evidence-verification.md) | Evidence verification via Nango | — |
| [2026-05-20-self-hosted-rest-api-phase1.md](./2026-05-20-self-hosted-rest-api-phase1.md) | Self-hosted REST API: auth + Memory/Knowledge endpoints | — |

## Brain architecture (blocked)

Reactive brain architecture phases. Cutover blocked on invariant fixes.

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-01-brain-architecture.md](./2026-06-01-brain-architecture.md) | 20 transactions, 8 invariants | Overview |
| [2026-06-01-phase2-implementation.md](./2026-06-01-phase2-implementation.md) | Core transaction implementations | Complete |
| [2026-06-01-phase4-lifecycle.md](./2026-06-01-phase4-lifecycle.md) | Node lifecycle transactions | Complete |
| [2026-06-01-phase5-layer-movement.md](./2026-06-01-phase5-layer-movement.md) | Layer promotion/demotion | Complete |
| [2026-06-01-phase6-query-recall.md](./2026-06-01-phase6-query-recall.md) | Query and recall transactions | Complete |
| [2026-06-01-phase7-cite-v2-epistemology.md](./2026-06-01-phase7-cite-v2-epistemology.md) | CITE v2 schema | Complete |
| [2026-06-02-phase8-reactions.md](./2026-06-02-phase8-reactions.md) | Reaction system | Complete |
| [2026-06-02-phase9-dagster-migration.md](./2026-06-02-phase9-dagster-migration.md) | Dagster job migration | Complete |
| [2026-06-03-brain-cutover-and-quality-fixes.md](./2026-06-03-brain-cutover-and-quality-fixes.md) | Wire MCP to brain, coverage reporting | Blocked |

## Future work

Specced or checkpointed for later implementation:

| Item | Spec/Note | Trigger |
|------|-----------|---------|
| **ML Products for Frontier Labs** | `docs/superpowers/specs/2026-05-23-ml-products-frontier-labs-design.md` | Post-fundraise |
| **Self-Hosted REST API Phase 2+** | `docs/superpowers/specs/2026-05-20-self-hosted-rest-api-design.md` | After Phase 1 |
| **Concepts** | `docs/superpowers/specs/2026-05-18-concepts-design.md` | Post-beta, retrieval quality degrades |

## Archive

Completed plans in `archive/` (120+ files). Recent:
- Embedding Batching Phase 1 (2026-06-05)
- Heat Utilization Phase 1 (2026-06-04)
- Enforcement Spine (2026-06-04)
- Multi-Format Skill Installation (2026-05-28)
- Harness-Agnostic Enforcement (2026-05-28)
- Self-Hosted Distribution Phase 2 (2026-05-26)
- Engagement Plans A-E (2026-05-25/26)

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria
