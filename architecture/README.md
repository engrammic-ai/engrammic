# Architecture Notes

## Knowledge Layer: :Finding vs :Fact

Two distinct node types carry Knowledge-layer semantics. They are not interchangeable.

### :Finding

Cluster/silo synthesis output from the RAG-era Custodian cycle. Currently active in production.

- Created by `custodian/consensus_promotion.py` via `CREATE_FINDING_FROM_COMMITMENT` (Cypher in `engine/queries.py`).
- Always carries `scope: "cluster" | "silo"` — it represents a synthesis over many claims within a cluster or silo boundary.
- The Custodian visit/promote cycle writes `:Claim:Commitment` nodes, then promotes them to `:Finding` once R2 consensus is reached at the cluster level.
- Not renamed or migrated. The RAG-era pipeline is active; a data migration of existing `:Finding` nodes offers no capability gain.

### :Fact

EAG-promoted Knowledge from a single `:Claim`. Implemented as an additional label on the existing `:Claim` node (`:Claim:Fact`), so all incoming/outgoing edges (REFERENCES, SUPERSEDES, DERIVED_FROM) are preserved without rewrite.

- Created when a `:Claim` accumulates enough evidence to satisfy `primitives.eag.epistemology.promotion.should_promote_r1` (single authoritative source, `raw_confidence >= 0.7`) or `should_promote_r2` (multi-source corroboration, aggregate confidence >= 0.8 with at least one authoritative source).
- Promotion sets `c.promoted_at` and `c.promotion_rule` on the node.
- Write path: `services/context.py::promote_claim_to_fact` → `db/queries.py::PROMOTE_CLAIM_TO_FACT`.
- The epistemology adapter lives in `custodian/fact_promotion.py`.
- The Dagster batch sweep asset is `pipelines/assets/fact_promotion.py`.

### Coexistence

Read tools that filter by `layer="knowledge"` return both `:Finding` and `:Claim:Fact` nodes, because the `layer` property is set on both at write time (`services/context.py` sets `props["layer"] = "knowledge"` for claims).

`:Finding` is cluster-scoped synthesis; `:Fact` is per-claim promotion from the EAG epistemology rules. The two paths operate independently and must not be merged.

### Cross-references

- Implementation plan: `context/plans/v1a-claim-fact-promotion.md`
- EAG paradigm and layer definitions: `../primitives/docs/`
- Promotion predicates: `../primitives/src/primitives/eag/epistemology/promotion.py`
- Index for `:Fact`: `src/context_service/db/indexes.py` (lines 54-56)
