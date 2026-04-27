# CAG Integration Audit — 2026-04-26

## Provenance

This audit was produced during the port session on 2026-04-26 that moved ~150 files from the `contextr` prototype (`NovusEdge/CTXR`, private) into this repo. The port session itself brought the codebase to 0 lint/type errors. This document records the remaining CAG integration gaps that were deferred — items that required design decisions beyond mechanical porting.

## Current State (What Was Inconsistent)

### Schema Consistency

**Fixed:** `db/schema.py` imported `CAGEdgeType`, `KnowledgeLabel`, `MemoryLabel` but not `RegistryLabel`. `LABEL_ENTITY` was a raw hardcoded string `"Entity"` instead of `RegistryLabel.ENTITY.value`.

**Fixed:** `engine/memgraph_store.py` had two hardcoded label sets:
- Line 73: `("Document", "Passage", "Claim", "Entity")` used to classify nodes in `_node_from_record`
- Line 762: `{"Document", "Passage", "Claim", "Entity", "Node"}` used in shortest-path node filtering
Neither was sourced from schema constants. The set was also recreated inside a static method on every call.

**Fixed:** `engine/queries.py` imported `LABEL_DOCUMENT` and `LABEL_ENTITY` from schema but missed `LABEL_PASSAGE`, `LABEL_CLAIM`, `IntelligenceLabel`, and `KnowledgeLabel`. Several Cypher strings used inline label literals:
- `UPSERT_DOCUMENT_AND_PASSAGES`: hardcoded `:Document`, `:Passage`, `DERIVED_FROM`
- `FLIP_DOCUMENT_COMMITTED_VERSION_GATED`: hardcoded `:Document`, `:Passage`, `DERIVED_FROM`
- `RECLASSIFY_DOCUMENT`, `TOMBSTONE_DOCUMENT`, `SWEEP_ORPHAN_DOCUMENTS`: hardcoded `:Document`, `:Passage`
- `GET_DOCUMENT_PASSAGE_IDS`: hardcoded `:Document`, `:Passage`
- All inference/phase-8 queries (`UPSERT_REASONING_CHAIN`, `FLIP_CHAIN_COMMITTED`, `UPSERT_COMMITMENT`, `FLIP_COMMITMENT_COMMITTED`, `CREATE_CRYSTALLIZED_INTO_EDGE`, `CREATE_DERIVED_FROM_EVIDENCE_EDGE`, `CHECK_CHAIN_DEPTH`, all erasure/compaction/consensus queries): hardcoded `:ReasoningChain`, `:Commitment`, `:Claim:Commitment`

**Fixed:** `db/custodian_read_queries.py` had no import from `db.schema`. Six Cypher strings used inline `n:Document OR n:Passage OR n:Claim` predicates instead of `content_union_predicate()`:
- `FETCH_CLUSTER_MEMBERS`, `COUNT_CLUSTER_MEMBERS`, `FETCH_NODE_BY_ID`
- `FETCH_NEIGHBORHOOD_SEED`, `FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE`
- `LIST_EDGES_OF_TYPE_IN_CLUSTER`, `FETCH_CLUSTER_MEMBER_IDS`

**Fixed:** `db/custodian_queries.py` had no import from `db.schema`. `FETCH_CLUSTERS_BY_LEVEL` used inline `n:Document OR n:Passage OR n:Claim`. `CITES_EDGE_CREATE_NODE` used `n:Document OR n:Passage OR n:Claim`.

### DB Queries Audit

**Already correct:** `db/queries.py` — all queries use schema constants imported from `db.schema`. The `BELONGS_TO` and `PART_OF` edges are plain strings not in `CAGEdgeType` (intentional — these are clustering-specific relationships). `EDGE_REFERENCES` remains a plain string `"REFERENCES"` in `db/schema.py` because it is not yet in `CAGEdgeType`.

**Already correct:** `clustering/queries.py` — uses `MEMBER_OF` (from `CAGEdgeType`) correctly per comment. `PART_OF` is intentionally a plain string for the inter-cluster hierarchy (not in `CAGEdgeType`).

### Prompts Consolidation

**Two separate loading mechanisms exist (no README):**

- **Custodian** (`custodian/prompt_loader.py`): YAML files under `config/prompts/custodian/*.yaml`, loaded via `load_prompt(path, **vars)` with lens support. Used by agents.py, supersession_parser.py, silo_synthesis.py.
- **Extraction + Clustering** (`config/config_loader.py` + `prompts.yaml`): Provider-preset system via `get_settings().prompt_preset` → `_get_extraction_preset()` / `_get_clustering_preset()`. Used by extraction/prompts.py, clustering/prompts.py.

The two mechanisms are intentionally different (custodian prompts need lens composition; extraction/clustering prompts need provider-preset switching). No README exists in `config/prompts/`.

### CAG Layer Integration

**Naming tension (documented, not changed):** `:Finding` in `custodian_queries.py` and across the codebase is the RAG-era Custodian output label. `:Fact` is the CAG Knowledge layer label (`KnowledgeLabel.FACT`). In the current system:
- `:Finding` = cluster-scoped custodian synthesis output (RAG-era, shipped, active)
- `:Fact` = CAG Knowledge layer promoted fact (defined in `primitives.schema`, no write path implemented yet)
- `CREATE_FINDING_FROM_COMMITMENT` (consensus promotion) creates a `:Finding` from a `:Claim:Commitment` — this is the CAG R2 promotion path, but the output uses the `:Finding` label rather than `:Fact`

The mapping is: RAG-era `:Finding` ≈ CAG `:Fact` functionally, but the label mismatch means the CAG layer definition in `db/indexes.py` (which indexes `:Fact`) has no write path yet. This needs a decision before implementing T5/T6 (CAG Claim→Fact promotion pipeline).

**Primitives epistemology usage:**
- `primitives.cag.epistemology.promotion` (`should_promote_r1`, `should_promote_r2`, `ClaimForPromotion`, `PromotionDecision`) — NOT used anywhere in context-service. The custodian's `promotion.py` implements its own Finding-level promotion (draft→published status flip), not Claim→Fact promotion.
- `primitives.cag.epistemology.supersession` (`should_supersede`, `detect_contradiction`) — NOT used. `custodian/supersession.py` implements supersession detection via LLM call, not via the pure-function primitives. The primitives are for structured fact-vs-fact comparison; the custodian implementation handles free-text content nodes.
- `primitives.cag.epistemology.confidence` — NOT used in context-service.

These are not bugs — the primitives epistemology layer targets a structured `:Claim`/`:Fact` graph that doesn't yet have a write path. They become relevant once CAG Claim→Fact promotion is implemented.

**Layer transition wiring (T1-T9):** No explicit transition-wiring code exists in context-service. The `consensus_promotion.py` implements a form of T3 (Claim:Commitment → Finding), and `promotion.py` implements Finding draft→published. T1 (store→Memory), T2 (Memory→Knowledge extraction), T4 (Knowledge→Wisdom synthesis) have no explicit wiring layer — they're implemented as Dagster asset pipelines. This is architecturally consistent.

**CAUSES / CORROBORATES:** `CAGEdgeType.CAUSES` and `CAGEdgeType.CORROBORATES` are defined in primitives but have no write path in context-service. `extraction/models.py:RelationshipType.CAUSES` duplicates `CAGEdgeType.CAUSES` as a local enum value — this is the entity-relationship extraction vocabulary, separate from CAG semantic edges. Not a bug but worth noting as a potential future alignment point.

## Changes Made

| File | Change |
|------|--------|
| `db/schema.py` | Added `RegistryLabel` import; `LABEL_ENTITY` now sourced from `RegistryLabel.ENTITY.value` |
| `engine/memgraph_store.py` | Added `LABEL_CLAIM`, `LABEL_PASSAGE` imports; replaced two hardcoded label sets with module-level `_CONTENT_LABEL_SET` and `_PATH_LABEL_SET` constants |
| `engine/queries.py` | Added `LABEL_CLAIM`, `LABEL_PASSAGE`, `IntelligenceLabel`, `KnowledgeLabel` imports; converted 12 Cypher constants from raw strings to f-strings using schema constants |
| `db/custodian_read_queries.py` | Added `content_union_predicate` import; converted 7 Cypher constants from inline label predicates to `content_union_predicate()` calls |
| `db/custodian_queries.py` | Added `content_union_predicate` import; converted `FETCH_CLUSTERS_BY_LEVEL` and `CITES_EDGE_CREATE_NODE` to use the helper |

All changes are mechanical string-to-constant substitutions. The generated Cypher is semantically identical.

## Remaining TODOs

### Clear follow-ups
1. **`EDGE_REFERENCES` gap** — `"REFERENCES"` in `db/schema.py` is not in `CAGEdgeType`. Either add `REFERENCES` to `CAGEdgeType` in primitives, or document it as a context-service-only edge type.
2. **`BELONGS_TO` / `PART_OF` edge inconsistency** — `db/queries.py` uses `BELONGS_TO` for clustering; `clustering/queries.py` uses `MEMBER_OF` (per `CAGEdgeType`). These are the same semantic relationship. One of these is wrong. `clustering/queries.py` has a comment noting `MEMBER_OF` is the correct CAG edge; `db/queries.py` should be migrated.
3. **Prompts README** — `config/prompts/custodian/` has no README. Add a brief one explaining the two-mechanism split (custodian YAML with lenses vs extraction/clustering provider presets).
4. **Pre-existing lint errors** — 23 ruff errors existed before this audit (ARG/SIM/F841 in embeddings, MCP tools, pipelines resources). Not introduced by this work but should be cleaned up.

### Needs discussion before implementing
5. **`:Finding` vs `:Fact` naming** — Decide whether the consensus promotion path should write `:Fact` (CAG canonical) or continue writing `:Finding` (RAG-era). Migration of existing `:Finding` nodes is non-trivial; a parallel-write pattern or a label-union read approach may be needed.
6. **`primitives.cag.epistemology` integration** — Once a `:Claim`→`:Fact` write path exists, `should_promote_r1`/`should_promote_r2` from primitives should replace the current `PromotionPlan`/`execute_promotion` which operates on Finding status flips. These are fundamentally different operations and should not be merged prematurely.
7. **`RelationshipType.CAUSES` alignment** — `extraction/models.py:RelationshipType` and `primitives.schema.edges.CAGEdgeType` overlap on `CAUSES`. If the extraction pipeline is expected to write CAG semantic edges directly (rather than `:ProposedEdge` nodes), `RelationshipType` could be replaced by `CAGEdgeType`. Currently they serve different purposes (LLM extraction vocabulary vs graph edge type registry).

## Open Questions

- Should `BELONGS_TO` (in `db/queries.py`) be migrated to `MEMBER_OF` (per CAG schema) before the next prod deploy, or deferred to a migration pass? Data in prod uses `BELONGS_TO` — a schema migration would be needed.
- Is `:Finding` intentionally kept as the RAG-era output label for the Custodian cycle, with `:Fact` reserved for the future structured promotion pipeline? If yes, this should be documented in `architecture/README.md` to prevent future confusion.
