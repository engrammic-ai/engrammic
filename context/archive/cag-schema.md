# CITE Node/Edge Schema Spec

**Status:** draft  
**Date:** 2026-04-26

This document specifies the CITE (Epistemic Augmented Generation architecture) schema for the primitives library. It defines node types, edge types, their properties, indexes, and constraints.

## Layers

All nodes belong to a persistence layer:

| Layer | Value | Description |
|-------|-------|-------------|
| Memory | `memory` | Experiences that fade |
| Knowledge | `knowledge` | Facts that persist until contradicted |
| Wisdom | `wisdom` | Beliefs that revise on evidence shift |
| Intelligence | `intelligence` | Ephemeral reasoning |
| Registry | `registry` | Entity, Predicate, Agent |
| Audit | `audit` | ErasureEvent, CalibrationEvent, BootstrapState |

---

## Node Types

### Memory Layer

#### `:Document`

Top-level ingested content container.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `org_id` | string | yes | Organization scope |
| `layer` | string | yes | Always `memory` |
| `content` | string | no | Raw text content |
| `title` | string | no | Document title |
| `kind` | string | no | `docs`, `paper`, `issue`, `spec`, `article`, `other` |
| `origin` | string | no | Source URL or path |
| `stale` | boolean | no | Soft-delete flag (default false) |
| `committed` | boolean | yes | Visible to retrieval (default true) |
| `created_at` | datetime | yes | Creation timestamp |
| `updated_at` | datetime | no | Last modification |

**Indexes:**
- `CREATE INDEX ON :Document(id);`
- `CREATE INDEX ON :Document(silo_id);`
- `CREATE INDEX ON :Document(org_id);`

---

#### `:Passage`

Chunked text segment extracted from a Document.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `org_id` | string | yes | Organization scope |
| `layer` | string | yes | Always `memory` |
| `content` | string | yes | Passage text |
| `doc_id` | string | yes | Parent document ID |
| `chunk_index` | int | no | Position in document |
| `importance` | float | no | PageRank score |
| `heat_score` | float | no | Usage-based temperature |
| `stale` | boolean | no | Soft-delete flag (default false) |
| `committed` | boolean | yes | Visible to retrieval (default true) |
| `created_at` | datetime | yes | Creation timestamp |

**Indexes:**
- `CREATE INDEX ON :Passage(id);`
- `CREATE INDEX ON :Passage(silo_id);`
- `CREATE INDEX ON :Passage(doc_id);`

**Qdrant:** Dense + SPLADE vectors stored in per-silo collection.

---

#### `:Utterance`

Agent-generated text (conversations, outputs).

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `memory` |
| `content` | string | yes | Utterance text |
| `agent_id` | string | no | Producing agent |
| `session_id` | string | no | Conversation session |
| `created_at` | datetime | yes | Creation timestamp |

**Indexes:**
- `CREATE INDEX ON :Utterance(id);`
- `CREATE INDEX ON :Utterance(silo_id);`

---

#### `:Event`

Discrete occurrence with temporal bounds.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `memory` |
| `content` | string | no | Event description |
| `event_type` | string | no | Classification |
| `occurred_at` | datetime | no | When event occurred |
| `created_at` | datetime | yes | Record creation |

**Multi-label combo:** `:Event:ReasoningTrace` for traced reasoning events.

---

### Knowledge Layer

#### `:Claim`

Extracted assertion from source content. The input to promotion.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `knowledge` |
| `fingerprint` | string | yes | sha256(subject\|predicate\|object) |
| `subject` | string | yes | Subject entity name |
| `predicate` | string | yes | Relation/property |
| `object` | string | no | Object entity or literal |
| `valid_from` | datetime | no | Temporal validity start |
| `valid_to` | datetime | no | Temporal validity end |
| `source_doc_id` | string | yes | Origin document |
| `source_passage_id` | string | yes | Origin passage |
| `confidence` | float | yes | Raw extraction confidence (0-1) |
| `source_tier` | string | no | `authoritative`, `validated`, `community`, `unknown` |
| `promoted_to_fact` | boolean | no | Has been promoted (default false) |
| `committed` | boolean | yes | Extraction committed (default true) |
| `created_at` | datetime | yes | Creation timestamp |

**Indexes:**
- `CREATE INDEX ON :Claim(id);`
- `CREATE INDEX ON :Claim(silo_id);`
- `CREATE INDEX ON :Claim(fingerprint);`
- `CREATE INDEX ON :Claim(silo_id, promoted_to_fact);`

**Constraints:**
- No uniqueness constraint on fingerprint (multiple claims can share same s/p/o from different sources).

**Multi-label combo:** `:Claim:Commitment` for cross-layer authored stance per D1.

---

#### `:Fact`

Promoted knowledge with aggregated confidence across sources.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `knowledge` |
| `fingerprint` | string | yes | sha256(subject_id\|predicate\|object_id_or_literal) — MERGE key |
| `subject_id` | string | yes | Subject entity ID |
| `predicate` | string | yes | Relation/property |
| `object_id` | string | no | Object entity ID (null when object is literal) |
| `object_literal` | string | no | Literal value when object is not an entity |
| `confidence` | float | yes | Aggregated confidence (noisy-OR across sources, cap 0.99) |
| `raw_confidence_max` | float | no | Max single-claim confidence |
| `source_count` | int | yes | Number of contributing claims |
| `authoritative_count` | int | no | Count of authoritative-tier sources |
| `promoted_via` | string | yes | `R1`, `R2`, `R3`, `R4` |
| `promoted_at` | datetime | yes | Promotion timestamp |
| `updated_at` | datetime | yes | Last update |
| `valid_from` | datetime | no | Temporal validity start |
| `valid_to` | datetime | no | Temporal validity end |
| `superseded` | boolean | no | Has been superseded (default false) |

**Indexes:**
- `CREATE INDEX ON :Fact(id);`
- `CREATE INDEX ON :Fact(silo_id);`
- `CREATE INDEX ON :Fact(fingerprint);`
- `CREATE INDEX ON :Fact(subject_id, predicate);` (contradiction lookup)

**Constraints:**
- Uniqueness on `fingerprint` within silo (MERGE key).

**Qdrant:** Dense vectors stored post-promotion (deferred to future phase).

---

### Wisdom Layer

#### `:Belief`

Synthesized stance that covers a cluster of Facts.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `wisdom` |
| `content` | string | yes | Belief statement |
| `confidence` | float | no | Belief confidence |
| `agent_id` | string | no | Declaring agent |
| `created_at` | datetime | yes | Creation timestamp |
| `updated_at` | datetime | no | Last revision |

---

#### `:Pattern`

Recurring structural/semantic pattern across Facts.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `wisdom` |
| `content` | string | no | Pattern description |
| `pattern_type` | string | no | Classification |
| `created_at` | datetime | yes | Creation timestamp |

---

#### `:Commitment`

Authored stance that can exist at Wisdom layer standalone.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `wisdom` |
| `content` | string | yes | Commitment statement |
| `agent_id` | string | yes | Declaring agent |
| `created_at` | datetime | yes | Creation timestamp |

**Note:** `:Claim:Commitment` is the canonical cross-layer node (Knowledge layer claim that is also an authored commitment).

---

### Intelligence Layer

#### `:ReasoningChain`

Ephemeral reasoning trace with crystallizations.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `intelligence` |
| `steps` | string (JSON) | no | Inlined reasoning steps |
| `query` | string | no | Triggering query |
| `agent_id` | string | no | Reasoning agent |
| `created_at` | datetime | yes | Creation timestamp |
| `crystallized_at` | datetime | no | When crystallized to Knowledge |

---

#### `:QueryContext`

Ephemeral query execution context.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `layer` | string | yes | Always `intelligence` |
| `query` | string | yes | Query text |
| `retrieved_ids` | list[string] | no | Retrieved node IDs |
| `created_at` | datetime | yes | Creation timestamp |

---

### Registry

#### `:Entity`

Named entity for entity resolution.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `name` | string | yes | Entity name |
| `entity_type` | string | no | Classification (person, org, concept, etc.) |
| `description` | string | no | Description |
| `qualified_name` | string | no | Fully qualified name |
| `file_path` | string | no | Source file (for code entities) |
| `importance` | float | no | PageRank score |
| `created_at` | datetime | yes | Creation timestamp |

**Indexes:**
- `CREATE INDEX ON :Entity(id);`
- `CREATE INDEX ON :Entity(silo_id);`
- `CREATE INDEX ON :Entity(name);` (case-insensitive lookup via toLower)

**Multi-label combo:** `:Entity:Agent` for agent entities.

---

#### `:Predicate`

Predicate registry for relation normalization.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | no | Per-silo or shared |
| `name` | string | yes | Predicate name |
| `description` | string | no | Semantics |
| `created_at` | datetime | yes | Creation timestamp |

---

#### `:Agent`

Agent identity (global, per-silo participation).

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `name` | string | yes | Agent name |
| `role` | string | no | `silo_principal`, `silo_admin`, `member`, `guest` |
| `trust_tier` | string | no | `authoritative`, `validated`, `community`, `unknown` |
| `created_at` | datetime | yes | Creation timestamp |

---

### Audit

#### `:ErasureEvent`

GDPR right-to-erasure audit trail.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `target_node_id` | string | yes | Erased node ID |
| `cascade_count` | int | no | Cascaded deletions |
| `requested_by` | string | no | Requesting agent/user |
| `erased_at` | datetime | yes | Erasure timestamp |

---

#### `:CalibrationEvent`

Confidence calibration audit.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `sigma` | float | no | Calibration sigma |
| `sample_count` | int | no | Sample size |
| `calibrated_at` | datetime | yes | Calibration timestamp |

---

### Operational

#### `:Cluster`

Leiden clustering membership container.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `level` | int | yes | Hierarchy level (1=FINE, 2=MEDIUM, 3=COARSE) |
| `community_id` | int | no | Leiden community ID |
| `summary` | string | no | Cluster summary |
| `key_topics` | list[string] | no | Topic keywords |
| `node_count` | int | no | Member count |
| `tier` | string | no | `HOT`, `WARM`, `COLD` |
| `last_custodian_pass_id` | string | no | Last visit pass |
| `last_custodian_run_at` | datetime | no | Last visit time |
| `created_at` | datetime | yes | Creation timestamp |
| `updated_at` | datetime | no | Last update |

**Indexes:**
- `CREATE INDEX ON :Cluster(id);`
- `CREATE INDEX ON :Cluster(silo_id);`
- `CREATE INDEX ON :Cluster(level);`

---

#### `:Silo`

Tenancy container.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `org_id` | string | yes | Owning organization |
| `name` | string | no | Silo name |
| `description` | string | no | Silo description |
| `cluster_generation` | int | no | Cluster rebuild counter |
| `created_at` | datetime | yes | Creation timestamp |

---

#### `:Finding`

Per-cluster visit output (RAG-era, audit role in EAG).

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Tenancy scope |
| `org_id` | string | yes | Organization scope |
| `scope` | string | yes | `cluster` or `silo` |
| `cluster_id` | string | no | Target cluster (null for silo-scope) |
| `pass_id` | string | yes | Producing pass |
| `version` | int | yes | Version number |
| `status` | string | yes | `draft`, `published` |
| `source` | string | yes | `custodian`, `extraction` |
| `summary` | string (JSON) | no | Stitched summary |
| `claims` | string (JSON) | no | Claim list |
| `quality_score` | float | no | Quality metric |
| `created_at` | datetime | yes | Creation timestamp |
| `updated_at` | datetime | yes | Last update |

**Indexes:**
- `CREATE INDEX ON :Finding(id);`
- `CREATE INDEX ON :Finding(silo_id);`
- `CREATE INDEX ON :Finding(org_id);`
- `CREATE INDEX ON :Finding(cluster_id);`

**Constraints:**
- `CREATE CONSTRAINT ON (f:Finding) ASSERT f.scope, f.cluster_id, f.silo_id IS UNIQUE;`

---

#### `:Pass`

Custodian pass ledger.

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `id` | string (uuid) | yes | Unique identifier |
| `silo_id` | string | yes | Target silo |
| `org_id` | string | yes | Organization scope |
| `cluster_generation` | int | no | Stamped generation at pass start |
| `status` | string | yes | `running`, `completed`, `failed`, `cancelled`, `crashed`, `budget_exceeded` |
| `started_at` | datetime | yes | Start time |
| `finalized_at` | datetime | no | End time |
| `cost_usd` | float | no | Accumulated cost |
| `visit_count` | int | no | Visit count |

**Indexes:**
- `CREATE INDEX ON :Pass(id);`
- `CREATE INDEX ON :Pass(silo_id);`

---

## Edge Types

### Provenance Edges

#### `DERIVED_FROM`

Tracks derivation of higher-layer nodes from lower-layer sources.

| Direction | Source | Target |
|-----------|--------|--------|
| `(higher)-[:DERIVED_FROM]->(lower)` | `:Fact`, `:Belief`, `:Claim` | `:Passage`, `:Document`, `:Utterance` |

| Property | Type | Description |
|----------|------|-------------|
| `created_at` | datetime | Edge creation |

**Invariant I1:** Every `:Fact` must have at least one `DERIVED_FROM` edge to a Memory-layer source.

---

#### `CITES`

Citation from a Finding to source content.

| Direction | Source | Target |
|-----------|--------|--------|
| `(f:Finding)-[:CITES]->(n)` | `:Finding` | `:Document`, `:Passage`, `:Claim` |

| Property | Type | Description |
|----------|------|-------------|
| `kind` | string | `primary`, `supporting` |

---

#### `SUPERSEDES`

Records when one node replaces another.

| Direction | Source | Target |
|-----------|--------|--------|
| `(new)-[:SUPERSEDES]->(old)` | `:Fact`, `:Finding` | `:Fact`, `:FindingHistory` |

| Property | Type | Description |
|----------|------|-------------|
| `reason` | string | `contradiction`, `revision`, `merge` |
| `contradicting_evidence_node_id` | string | Evidence node (for contradiction) |
| `superseded_at` | datetime | When superseded |

**Invariant I5:** Every `SUPERSEDES` edge with `reason='contradiction'` must carry `contradicting_evidence_node_id`.

---

#### `PROMOTED_FROM`

Records layer promotion.

| Direction | Source | Target |
|-----------|--------|--------|
| `(higher)-[:PROMOTED_FROM]->(lower)` | `:Fact` | `:Claim` |

| Property | Type | Description |
|----------|------|-------------|
| `rule` | string | `R1`, `R2`, `R3`, `R4` |
| `promoted_at` | datetime | Promotion timestamp |

---

#### `CRYSTALLIZED_INTO`

Links Intelligence-layer reasoning to Knowledge-layer output.

| Direction | Source | Target |
|-----------|--------|--------|
| `(chain)-[:CRYSTALLIZED_INTO]->(fact)` | `:ReasoningChain` | `:Fact`, `:Claim` |

| Property | Type | Description |
|----------|------|-------------|
| `crystallized_at` | datetime | When crystallized |

---

### Structure Edges

#### `MEMBER_OF`

Cluster membership.

| Direction | Source | Target |
|-----------|--------|--------|
| `(node)-[:MEMBER_OF]->(cluster)` | `:Fact` | `:Cluster` |

**Note:** Currently clustering operates on `:Claim` via `BELONGS_TO`. `:Fact` membership deferred.

---

#### `BELONGS_TO`

Content node to cluster membership.

| Direction | Source | Target |
|-----------|--------|--------|
| `(node)-[:BELONGS_TO]->(cluster)` | `:Document`, `:Passage`, `:Claim`, `:Entity` | `:Cluster` |

| Property | Type | Description |
|----------|------|-------------|
| `weight` | float | Membership strength |
| `created_at` | datetime | Edge creation |

---

#### `PART_OF`

Cluster hierarchy.

| Direction | Source | Target |
|-----------|--------|--------|
| `(child)-[:PART_OF]->(parent)` | `:Cluster` | `:Cluster` |

| Property | Type | Description |
|----------|------|-------------|
| `created_at` | datetime | Edge creation |

---

#### `ABOUT`

Finding to cluster linkage.

| Direction | Source | Target |
|-----------|--------|--------|
| `(finding)-[:ABOUT]->(cluster)` | `:Finding` | `:Cluster` |

---

#### `SUMMARIZES`

Silo-scope finding linkage.

| Direction | Source | Target |
|-----------|--------|--------|
| `(finding)-[:SUMMARIZES]->(silo)` | `:Finding` | `:Silo` |

---

### Entity Resolution Edges

#### `MENTIONS`

Links Claims to mentioned Entities.

| Direction | Source | Target |
|-----------|--------|--------|
| `(claim)-[:MENTIONS]->(entity)` | `:Claim` | `:Entity` |

---

#### `USES_PREDICATE`

Links Claims/Facts to predicate registry.

| Direction | Source | Target |
|-----------|--------|--------|
| `(node)-[:USES_PREDICATE]->(predicate)` | `:Claim`, `:Fact` | `:Predicate` |

---

#### `EXTRACTED_FROM`

Links Claim to source Passage/Document.

| Direction | Source | Target |
|-----------|--------|--------|
| `(claim)-[:EXTRACTED_FROM]->(source)` | `:Claim` | `:Passage`, `:Document` |

---

### Synthesis Edges

#### `SYNTHESIZED_FROM`

Links synthesized Belief to source Facts.

| Direction | Source | Target |
|-----------|--------|--------|
| `(belief)-[:SYNTHESIZED_FROM]->(fact)` | `:Belief` | `:Fact` |

---

#### `COVERS`

Links Belief to the Cluster it summarizes.

| Direction | Source | Target |
|-----------|--------|--------|
| `(belief)-[:COVERS]->(cluster)` | `:Belief` | `:Cluster` |

---

### Agent Edges

#### `DECLARED_BY`

Links authored nodes to declaring agent.

| Direction | Source | Target |
|-----------|--------|--------|
| `(node)-[:DECLARED_BY]->(agent)` | `:Commitment`, `:Claim:Commitment` | `:Agent` |

---

### Operational Edges

#### `CLAIMED`

Pass-to-cluster visit ledger.

| Direction | Source | Target |
|-----------|--------|--------|
| `(pass)-[:CLAIMED]->(cluster)` | `:Pass` | `:Cluster` |

| Property | Type | Description |
|----------|------|-------------|
| `claimed_at` | datetime | When claimed |

---

#### `CONTRADICTS`

Explicit contradiction between Claims.

| Direction | Source | Target |
|-----------|--------|--------|
| `(claim_a)-[:CONTRADICTS]->(claim_b)` | `:Claim` | `:Claim` |

| Property | Type | Description |
|----------|------|-------------|
| `id` | string | Edge ID |

---

## Index Summary

```cypher
-- Document
CREATE INDEX ON :Document(id);
CREATE INDEX ON :Document(silo_id);
CREATE INDEX ON :Document(org_id);

-- Passage
CREATE INDEX ON :Passage(id);
CREATE INDEX ON :Passage(silo_id);
CREATE INDEX ON :Passage(doc_id);

-- Claim
CREATE INDEX ON :Claim(id);
CREATE INDEX ON :Claim(silo_id);
CREATE INDEX ON :Claim(fingerprint);
CREATE INDEX ON :Claim(silo_id, promoted_to_fact);

-- Fact
CREATE INDEX ON :Fact(id);
CREATE INDEX ON :Fact(silo_id);
CREATE INDEX ON :Fact(fingerprint);
CREATE INDEX ON :Fact(subject_id, predicate);

-- Entity
CREATE INDEX ON :Entity(id);
CREATE INDEX ON :Entity(silo_id);

-- Cluster
CREATE INDEX ON :Cluster(id);
CREATE INDEX ON :Cluster(silo_id);
CREATE INDEX ON :Cluster(level);

-- Finding
CREATE INDEX ON :Finding(id);
CREATE INDEX ON :Finding(silo_id);
CREATE INDEX ON :Finding(org_id);
CREATE INDEX ON :Finding(cluster_id);

-- Pass
CREATE INDEX ON :Pass(id);
CREATE INDEX ON :Pass(silo_id);
```

## Constraint Summary

```cypher
-- Finding uniqueness (cluster-scope)
CREATE CONSTRAINT ON (f:Finding) ASSERT f.scope, f.cluster_id, f.silo_id IS UNIQUE;
```
