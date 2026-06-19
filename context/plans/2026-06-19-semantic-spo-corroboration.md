# Semantic SPO Corroboration

**Status**: Draft  
**Created**: 2026-06-19  
**Goal**: Enable organic corroboration where semantically equivalent claims (different wording, same meaning) automatically corroborate each other.

## Problem

Current corroboration uses exact string matching on SPO triples:
```cypher
WHERE c.properties.subject = new.properties.subject
  AND c.properties.predicate = new.properties.predicate
  AND c.properties.object = new.properties.object
```

This fails for semantically equivalent claims:
- "Caching reduces database load" -> `(caching, reduces, database load)`
- "Database load is reduced by caching" -> `(database load, is_reduced_by, caching)`

These should corroborate but don't.

## Solution: Embedding-based SPO Similarity

### Core Idea

1. Embed the SPO triple as a single semantic vector
2. On new claim, find existing claims with similar SPO embeddings (cosine > threshold)
3. Count distinct evidence across semantically-similar claims

### Design

#### 1. SPO Embedding Generation

When storing a claim with SPO:
```python
spo_text = f"{subject} {predicate} {object}"
spo_embedding = await embedding_service.embed(spo_text)
```

Store as `spo_embedding` property on the Claim node.

#### 2. SPO Similarity Search

Use Qdrant's vector search with a filter:
```python
similar_claims = await qdrant.search(
    collection="spo_vectors",  # or use existing collection with namespace
    query_vector=new_spo_embedding,
    filter={"silo_id": silo_id, "state": "ACTIVE"},
    score_threshold=0.85,  # tune this
    limit=100,
)
```

#### 3. Corroboration Count

```python
# Get all evidence URIs from semantically-similar claims
evidence_set = set()
for claim in similar_claims:
    evidence_set.update(claim.properties.evidence)

corroboration_count = len(evidence_set)
should_promote = corroboration_count >= PROMOTION_THRESHOLD
```

### Implementation Options

#### Option A: Separate Qdrant Collection

Create `spo_vectors` collection specifically for SPO embeddings:
- Pros: Clean separation, optimized for SPO search
- Cons: Another collection to manage, sync issues

#### Option B: Named Vector in Existing Collection

Add `spo` as a named vector alongside `content`:
```python
qdrant.upsert(
    collection="context_vectors",
    points=[{
        "id": claim_id,
        "vector": {
            "content": content_embedding,
            "spo": spo_embedding,
        },
        "payload": {...}
    }]
)
```
- Pros: Single collection, atomic updates
- Cons: Requires hybrid mode (already enabled)

#### Option C: Graph-based Clustering (Deferred)

Use Memgraph Leiden clustering on SPO similarity:
- Pros: Leverages existing infra, handles drift over time
- Cons: Batch process, not real-time

**Recommendation**: Option B (named vector) for real-time corroboration.

### Schema Changes

Claim node gains:
- `spo_embedding: list[float]` - 768-dim vector (or match embedding model dims)

Qdrant collection `context_vectors` gains:
- Named vector `spo` alongside existing `content` vector

### Query Flow

```
store_claim() called
  |
  v
Extract SPO triple (existing)
  |
  v
Generate SPO embedding (NEW)
  |
  v
Search Qdrant for similar SPO vectors (NEW)
  |
  v
Collect evidence URIs from matches
  |
  v
Count distinct evidence = corroboration_count
  |
  v
If >= threshold, promote to Fact
```

### Similarity Threshold Tuning

Start with 0.85 cosine similarity:
- Too low (0.7): unrelated claims match
- Too high (0.95): only near-identical phrasings match

Expose as config: `CORROBORATION_SPO_SIMILARITY_THRESHOLD`

### Migration

Existing claims without `spo_embedding`:
1. Backfill via Dagster job (batch embed existing SPO triples)
2. Or lazy-compute on first corroboration check

### Tasks

1. [ ] Add `spo` named vector to Qdrant collection schema
2. [ ] Generate SPO embedding in `store_claim()` 
3. [ ] Store SPO embedding in Qdrant (upsert with named vector)
4. [ ] Update `check_corroboration()` to use vector similarity
5. [ ] Add similarity threshold config
6. [ ] Backfill job for existing claims
7. [ ] Tests for semantic corroboration

### Estimated Effort

- Core implementation: 2-3 hours
- Testing + tuning: 1-2 hours
- Backfill job: 1 hour

## Appendix: Alternative Approaches Considered

### Canonicalization (Quick Fix)

Normalize SPO before comparison:
- Lowercase
- Lemmatize (reduces -> reduce)
- Sort subject/object alphabetically
- Active voice transformation

Pros: Simple, no embedding cost  
Cons: Misses semantic equivalence ("reduces" vs "decreases")

### Full Claim Clustering

Use existing claim embeddings + Leiden clustering.

Pros: Already have infrastructure  
Cons: Full content embedding != SPO meaning, batch not real-time
