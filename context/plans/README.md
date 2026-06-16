# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-06-16)

**Focus:** mem0 benchmark - TEMPR 4-channel retrieval complete, benchmark remaining

**Recent:**
- v2.41 Wisdom/Intelligence layer activation (complete)
- v2.40 Trigram search integration for BM25 channel (complete)
- v2.39 TEMPR 4-channel retrieval - BM25, temporal, PPR, cross-encoder (complete)
- v2.38 Mypy strict: 115 -> 0 errors (complete)

## Active plans

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-09-longmemeval-v2-harness.md](./2026-06-09-longmemeval-v2-harness.md) | Official LongMemEval-V2 harness with Engrammic adapter | Ready |
| [recall-quality-improvement.md](./recall-quality-improvement.md) | Question-answer asymmetry research, query expansion | Draft |
| [polish-audit-2026-06-08.md](./polish-audit-2026-06-08.md) | 7 critical + high findings from codebase audit | Triage |

## Benchmark (next priority)

- [ ] Create epistemic slice test cases (supersession, contradiction, abstention)
- [ ] Run benchmark: Engrammic full vs baseline vs mem0
- [ ] Document benchmark results

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

Reactive brain architecture phases. Cutover blocked on invariant fixes. Phases 2-9 complete and archived.

| Plan | Description | Status |
|------|-------------|--------|
| [2026-06-01-brain-architecture.md](./2026-06-01-brain-architecture.md) | 20 transactions, 8 invariants | Overview |
| [2026-06-03-brain-cutover-and-quality-fixes.md](./2026-06-03-brain-cutover-and-quality-fixes.md) | Wire MCP to brain, coverage reporting | Blocked |

## Future work

Specced or checkpointed for later implementation:

| Item | Spec/Note | Trigger |
|------|-----------|---------|
| **ML Products for Frontier Labs** | `docs/superpowers/specs/2026-05-23-ml-products-frontier-labs-design.md` | Post-fundraise |
| **Self-Hosted REST API Phase 2+** | `docs/superpowers/specs/2026-05-20-self-hosted-rest-api-design.md` | After Phase 1 |
| **Concepts** | `docs/superpowers/specs/2026-05-18-concepts-design.md` | Post-beta, retrieval quality degrades |

## Archive

Completed plans in `archive/` (135+ files). Recent:
- TEMPR parity sprint - 4-channel retrieval (2026-06-16)
- Wisdom/Intelligence layer activation (2026-06-14)
- Trigram search integration (2026-06-13)
- Read-path epistemic fusion step 1 (2026-06-11)
- Brain architecture phases 2-9 (2026-06-01/02)
- Embedding Batching Phase 1 (2026-06-05)

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria
