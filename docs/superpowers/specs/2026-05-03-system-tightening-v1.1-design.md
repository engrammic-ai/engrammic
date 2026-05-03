# System Tightening v1.1 Design

Three improvements to tighten the context service: semantic filtering for temporal queries, Knowledge-layer clustering, and edge type validation.

## 1. context_history Semantic Filtering

**Problem:** `temporal_query` accepts a `query` param but ignores it. Results are recency-ordered only, with no relevance filtering.

**Decision:** Qdrant pre-filter with recency sort.

| Approach | Verdict |
|----------|---------|
| Threshold filter (drop below similarity score) | Rejected: threshold tuning is fragile |
| Top-N pre-filter (fetch 3x, rank, trim) | Rejected: extra compute, no infra reuse |
| **Qdrant pre-filter** | **Accepted**: leverages existing vector index |

**Design:**
1. Embed the query via `self._embedding.embed_query(query)`
2. Query Qdrant for candidate node IDs (top `3 * top_k`)
3. Pass candidate IDs to Memgraph temporal query as a filter
4. Return results sorted by `valid_from DESC` (recency)

**Behavior:**
- Semantic filtering removes irrelevant nodes
- Recency ordering preserved (temporal is the contract)
- Not configurable; agents wanting pure relevance use `lookup` or `query`

**Files:**
- `src/context_service/services/context.py` (modify `temporal_query`)
- `src/context_service/db/queries.py` (add filtered temporal query variant)

## 2. Clustering Scope

**Problem:** Clustering includes all content nodes (Document, Passage, Claim, Entity). This mixes unvalidated Memory content into Wisdom synthesis.

**Decision:** Cluster Knowledge layer only, with configurable param.

| Approach | Verdict |
|----------|---------|
| Hard filter to `:Fact` only | Rejected: breaking change |
| **Layer param with Knowledge default** | **Accepted**: flexible, backward-compat |
| Separate pipelines per layer | Rejected: infra complexity |

**Design:**
- Add `target_layers: list[Layer] = [Layer.KNOWLEDGE]` param to `ClusteringService.run_pipeline`
- Modify clustering queries to filter by layer label (`:Fact`, `:Claim`)
- Synthesis follows `DERIVED_FROM` edges for Memory context but clusters Knowledge only

**Rationale:** EAG spec states "Knowledge to Wisdom via synthesis (cluster density threshold)". Wisdom emerges from validated Facts, not raw Documents.

**Files:**
- `src/context_service/clustering/service.py` (add param, filter logic)
- `src/context_service/clustering/queries.py` (layer-filtered queries)

## 3. EdgeTypeMatrix Validation

**Problem:** `ExtractionSchema.ALLOWED_TUPLES` is empty; all `(source_type, edge_label, target_type)` combinations pass validation. Bad extractions slip through.

**Decision:** Embedding classifier maps entity types to classes; matrix validates at class level.

| Approach | Verdict |
|----------|---------|
| Keyword/regex mapping | Rejected: misses novel types |
| **Embedding classifier** | **Accepted**: handles novel types, fast |
| LLM classifier | Rejected: slow/expensive for inline validation |

**Type Classes:**

| Class | Example Types |
|-------|---------------|
| Agent | Person, User, Bot, Team, Engineer |
| Organization | Company, Department, Startup, Group |
| Artifact | Document, File, Code, Module, API |
| Concept | Topic, Theme, Idea, Pattern, Goal |
| Event | Meeting, Deployment, Incident, Release |
| Location | City, Region, Address, Country |

**Validation Matrix (per RelationshipType enum):**

| Relationship | Valid Source | Valid Target | Notes |
|--------------|--------------|--------------|-------|
| COMPOSES | ANY | Artifact, Organization | X is part of Y |
| DEPENDS_ON | Artifact, Concept | Artifact, Concept | X requires Y |
| DERIVES_FROM | ANY | ANY | provenance, permissive |
| SPECIALIZES | ANY | ANY | X is a kind of Y |
| INSTANTIATES | ANY | Concept | X is instance of type Y |
| CAUSES | Event, Agent | ANY | X triggers Y |
| PREVENTS | Agent, Artifact, Concept | Event, Concept | X blocks Y |
| CORROBORATES | ANY | ANY | evidence, permissive |
| CONTRADICTS | ANY | ANY | conflict, permissive |
| REFERENCES | ANY | ANY | mention, permissive |
| RELATED_TO | ANY | ANY | fallback, permissive |

**Implementation:**
1. Pre-compute class centroid embeddings (one-time, store in config or code)
2. At extraction time, embed entity type strings
3. Classify via cosine similarity to nearest centroid
4. Validate edge against matrix; reject if invalid

**Files:**
- `src/context_service/extraction/models.py` (populate `ALLOWED_TUPLES`, add classifier)
- `src/context_service/extraction/type_classifier.py` (new: embedding-based classifier)
- `src/context_service/extraction/class_centroids.json` (new: precomputed centroids)

## Verification

```bash
just check                    # lint + typecheck
just test                     # unit tests

# Manual verification:
# 1. temporal_query: call with query string, verify irrelevant nodes filtered
# 2. clustering: run pipeline, verify only :Fact/:Claim nodes clustered
# 3. edge validation: extract edge with invalid type pairing, verify rejection
```
