# Architecture Decisions

## Finding vs Fact: Label Mapping

The codebase uses two distinct labels for validated knowledge, reflecting the system's evolution from RAG-era to EAG:

| Label | Origin | Purpose | Write Path |
|-------|--------|---------|------------|
| `:Finding` | RAG-era | Cluster-scoped custodian synthesis | `consensus_promotion.py` (Claim:Commitment -> Finding) |
| `:Fact` | EAG | Single-claim promotion via R1/R2 rules | `fact_promotion.py` (Claim -> Claim:Fact) |

Both labels coexist and serve different workflows:

- **Finding**: Output of the custodian's cluster synthesis pass. Multiple claims within a cluster are synthesized into a Finding, which then goes through draft -> published status promotion. Used for aggregate knowledge.

- **Fact**: Output of the EAG Claim -> Fact promotion pipeline. A single claim with sufficient evidence and confidence (evaluated via `primitives.eag.epistemology.promotion`) gets the `:Fact` label added. Used for individually validated claims.

## Primitives Epistemology Integration

The `primitives.eag.epistemology` module provides pure, deterministic functions for knowledge adjudication. Integration points in context-service:

| Module | Primitives Used | Location |
|--------|-----------------|----------|
| `confidence` | `combined_confidence`, `noisy_or_aggregate` | `custodian/fact_promotion.py`, `custodian/handlers/consensus.py` |
| `promotion` | `should_promote_r1`, `should_promote_r2` | `custodian/fact_promotion.py` |
| `supersession` | `should_supersede`, `FactForSupersession` | `custodian/supersession.py` (structured SPO path) |

The supersession module uses a dual-path approach: structured comparison via primitives for SPO-formatted claims, LLM fallback for free-text content.
