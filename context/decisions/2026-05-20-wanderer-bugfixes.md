# ADR: Wanderer Bugfixes

**Date:** 2026-05-20  
**Status:** Accepted  
**Deciders:** User, Claude  

## Context

Codebase exploration using the `engrammic:explore-codebase` skill discovered three bugs in the belief/revision subsystem. All three affect data integrity or quality of the Wisdom layer.

## Decisions

### 1. ID Collision: Use Operation Namespace

**Decision:** Add `operation` parameter to `_make_revised_belief_id` to namespace revision vs split IDs.

**Alternatives considered:**
- UUID for splits: Loses determinism
- Composite counter: Requires schema change

**Rationale:** Minimal change, preserves determinism, zero migration.

### 2. magnitude_pct: Thread Parameter from Caller

**Decision:** Add `cosine_distance` parameter to `revise_belief()`, callers pass from `RevisionCheckResult`.

**Alternatives considered:**
- Recompute inside `revise_belief`: Wasteful, already computed upstream

**Rationale:** Caller already has the value; just thread it through.

### 3. Word Overlap: Replace with Embedding Similarity

**Decision:** Replace word co-occurrence with cosine similarity on `centroid_embedding`.

**Alternatives considered:**
- Stopword filter: Still fundamentally lexical, would miss domain terms
- TF-IDF weighting: Middle ground but still lexical

**Rationale:** We already store embeddings. Semantic similarity is what we actually want to measure. The word-based approach was a placeholder that should have been replaced earlier.

**Threshold:** 0.85 default. This is conservative - high similarity required before considering merge. Configurable via settings for tuning.

## Consequences

- ID collision bug eliminated permanently
- MetaObservations now contain accurate drift magnitude
- Belief merge false positives significantly reduced
- Slight increase in compute for merge detection (embedding comparison vs string split), but we're comparing stored vectors, not generating new ones

## References

- Spec: `docs/superpowers/specs/2026-05-20-wanderer-bugfixes-design.md`
- Findings stored in Engrammic: `recall(tags=["engrammic-cs", "bug"])`
