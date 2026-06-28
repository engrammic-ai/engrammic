# Implementation Plans

Active implementation plans for context-service. Completed plans are moved to `archive/`.

## Current state (2026-06-28)

**Focus:** BEAM benchmark (Antler gate), batch API for seeding

**Recent completions:**
- Embedding quality + source verification - PR #80
- Multi-agent coherence v2 (full) - conflict detection, resolution verbs, agents tool, recall filters
- Evidence stub nodes for file:// and urn:// URIs
- Multi-agent coherence v1 (authored provenance + conflict detection) - PR #71
- SAGE restructure (Promoter/Synthesizer/Decayer/Detector) - PRs #68-70
- Recall consolidation + v2 synthesis trigger - PR #65

## Benchmark (next priority)

- [ ] Create epistemic slice test cases (supersession, contradiction, abstention)
- [ ] Run benchmark: Engrammic full vs baseline vs mem0
- [ ] Document benchmark results

## Active plans

| Plan | Description | Status |
|------|-------------|--------|
| [Batch API](../docs/superpowers/plans/2026-06-27-batch-api.md) | POST /batch/remember + /batch/learn for bulk ingestion | Ready |
| [2026-06-09-longmemeval-v2-harness.md](./2026-06-09-longmemeval-v2-harness.md) | Official LongMemEval-V2 harness with Engrammic adapter | Ready |

## Draft / design

| Plan | Description | Status |
|------|-------------|--------|
| [../review/2026-06-24-heat-ranking-research.md](../review/2026-06-24-heat-ranking-research.md) | Heat as PPR seed boost, synonymy edges, degree normalization | Consider |
| [2026-06-20-retrieval-remaining-work.md](./2026-06-20-retrieval-remaining-work.md) | Retrieval quality gaps | Spec |
| [2026-06-12-longmemeval-epistemic-harness.md](./2026-06-12-longmemeval-epistemic-harness.md) | LongMemEval with epistemic extensions | Draft |

## Pending (not started)

| Plan | Description | Blocker |
|------|-------------|---------|
| [2026-06-05-admin-dashboard.md](./2026-06-05-admin-dashboard.md) | Operator dashboard (memory state, usage, health) | REST API Phase 1 |
| [2026-06-09-standalone-architecture.md](./2026-06-09-standalone-architecture.md) | Standalone deployment architecture | - |
| [standalone-installer.md](./standalone-installer.md) | Standalone installer design | - |

## Reference

| Plan | Description |
|------|-------------|
| [2026-06-01-brain-architecture.md](./2026-06-01-brain-architecture.md) | 20 transactions, 8 invariants (complete, reference doc) |
| [2026-06-09-longmemeval-retrieval.md](./2026-06-09-longmemeval-retrieval.md) | LongMemEval retrieval notes |

## Future work

Specced or checkpointed for later implementation:

| Item | Spec/Note | Trigger |
|------|-----------|---------|
| **ML Products for Frontier Labs** | `docs/superpowers/specs/2026-05-23-ml-products-frontier-labs-design.md` | Post-fundraise |
| **Concepts** | `docs/superpowers/specs/2026-05-18-concepts-design.md` | Post-beta, retrieval quality degrades |

## Archive

Completed plans in `archive/` (160+ files). Recent:
- Embedding quality + source verification (2026-06-28)
- Multi-agent coherence v1 (2026-06-22)
- SAGE restructure - Promoter/Synthesizer/Decayer/Detector (2026-06-21)
- Recall consolidation + v2 synthesis (2026-06-20)
- Cascade invalidation fixes (2026-06-22)
- TEMPR parity sprint - 4-channel retrieval (2026-06-16)

## Plan format

Each plan should include:
- Goal and scope
- Phase branch name
- Tasks in priority order
- Out of scope / deferred items
- Done criteria
