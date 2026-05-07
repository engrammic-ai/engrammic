# EAG Transition Types

Reference for the 9 transition types in the EAG paradigm. Source: `primitives/context/specs/03-transitions.md`.

## Diagram

```
Memory --- T1 extract ---> Knowledge --- T3 synthesize ---> Wisdom
  |                           |                              |
  T8/T9 decay                 T2 supersede                   T4 revise
                              (K->K)                         (W->W)

Intelligence -- T5 consensus --> Knowledge
Intelligence -- T6 trace ------> Memory
Intelligence -- T7 commit -----> Wisdom
```

## Catalogue

| # | Name | From | To | Trigger | Execution |
|---|------|------|----|---------|-----------|
| T1 | extract | Memory | Knowledge | passage is hot OR source-changed OR queried | signal-driven, heat-ranked |
| T2 | supersede | Knowledge | Knowledge | new Fact conflicts with existing | eager (sync in validator) |
| T3 | synthesize | Knowledge | Wisdom | cluster density >= N, no Belief covers it | signal-driven |
| T4 | revise | Wisdom | Wisdom | distribution shift >= M% | signal-driven, creates new Belief (not in-place) |
| T5 | consensus | Intelligence | Knowledge | >= K chains from >= J agents agree | lazy, batched |
| T6 | trace | Intelligence | Memory | reasoning chain completes | batched post-session |
| T7 | commit | Intelligence | Wisdom | agent declares a stance | eager |
| T8 | decay | Memory | (none) | time-based retrieval weight -> 0 | compute-at-query |
| T9 | hard-delete | Memory | (none) | age > 2x decay class OR GDPR | scheduled GC |

## Execution Rules

- **Eager**: T2 (supersession), T7 (commit) — correctness-critical
- **Signal-driven**: T1, T3, T4 — optimization, heat-ranked
- **Batched/lazy**: T5, T6, T8, T9 — housekeeping

## Provenance Edges

Each transition writes edges to preserve audit trail:

| Transition | Edge | Direction |
|------------|------|-----------|
| T1 extract | `DERIVED_FROM` | Claim -> Passage |
| T2 supersede | `SUPERSEDES` | Fact_new -> Fact_old |
| T3 synthesize | `SYNTHESIZED_FROM` | Belief -> Fact (>= N) |
| T5 consensus | `PROMOTED_FROM` | Fact -> ReasoningChain |
| T6 trace | `DERIVED_FROM_EVIDENCE` | Chain -> Document/Passage/Claim |
| T7 commit | `DECLARED_BY` | Commitment -> Agent |

## T3 vs T7 (the common confusion)

**T3 (synthesize)**: System-derived. Custodian sees corroborated facts, infers higher-order belief.
- Created by system, not agent
- Can be invalidated if underlying facts change
- `kind: "pattern"` in implementation

**T7 (commit)**: Agent-authored. Agent explicitly takes a stance.
- Created by agent directly
- Persists until agent retracts
- `kind: "rule"` in implementation

Both produce `:Commitment` nodes but serve different epistemic purposes.

## Implementation Status

| Transition | Implemented | Location |
|------------|-------------|----------|
| T1 extract | Yes | `extraction/service.py`, Dagster assets |
| T2 supersede | Yes | `custodian/supersession.py` |
| T3 synthesize | Partial | `clustering/service.py` (needs kind field) |
| T4 revise | Yes | `custodian/supersession.py` |
| T5 consensus | Yes | `custodian/consensus_promotion.py` |
| T6 trace | Yes | `context_crystallize.py` |
| T7 commit | Yes | `context_store.py` wisdom layer |
| T8 decay | Yes | `signals/freshness.py` |
| T9 hard-delete | Yes | `pipelines/assets/gc_*.py` |
