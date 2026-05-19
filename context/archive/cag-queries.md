# EAG Query Catalog

**Status:** draft  
**Date:** 2026-04-26

This document catalogs the Cypher queries required for EAG operations in the primitives library. Queries are grouped by operation type. Each entry includes the query name, purpose, parameters, return shape, and the Cypher template.

---

## Read Queries

### `FETCH_CURRENT_FINDING_CLUSTER_SCOPE`

Look up the prior `:Finding` for a cluster-scope `(scope, cluster_id, silo_id)` triple.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `scope` | string | Always `"cluster"` |
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |

**Returns:** Single row or null
| Field | Type |
|-------|------|
| `id` | string |
| `version` | int |
| `claims` | string (JSON) |
| `summary` | string (JSON) |
| `pass_id` | string |
| `quality_score` | float |

```cypher
MATCH (f:Finding {scope: $scope, cluster_id: $cluster_id, silo_id: $silo_id})
RETURN f.id AS id,
       f.version AS version,
       f.claims AS claims,
       f.summary AS summary,
       f.pass_id AS pass_id,
       f.quality_score AS quality_score
LIMIT 1
```

---

### `FETCH_CURRENT_FINDING_SILO_SCOPE`

Look up the prior `:Finding` for a silo-scope `(scope, silo_id)` pair.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `scope` | string | Always `"silo"` |
| `silo_id` | string | Silo ID |

**Returns:** Single row or null (same shape as cluster-scope)

```cypher
MATCH (f:Finding {scope: $scope, silo_id: $silo_id})
WHERE f.cluster_id IS NULL
RETURN f.id AS id,
       f.version AS version,
       f.claims AS claims,
       f.summary AS summary,
       f.pass_id AS pass_id,
       f.quality_score AS quality_score
LIMIT 1
```

---

### `FETCH_CLUSTERS_BY_LEVEL`

Fetch clusters for a silo at a given hierarchy level, with member counts.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |
| `level` | int | Cluster level (1=FINE, 2=MEDIUM, 3=COARSE) |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `cluster_id` | string |
| `level` | int |
| `member_count` | int |
| `naive_summary` | string |

```cypher
MATCH (c:Cluster {silo_id: $silo_id})
WHERE c.level = $level
MATCH (n)-[:BELONGS_TO]->(c)
WHERE (n:Document OR n:Passage OR n:Claim) AND n.silo_id = $silo_id
WITH c, count(n) AS member_count
RETURN c.id AS cluster_id,
       c.level AS level,
       member_count,
       c.summary AS naive_summary
ORDER BY member_count DESC
```

---

### `FETCH_CHILD_FINDING_SUMMARIES`

Fetch published/extraction child finding summaries for a parent cluster.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `cluster_id` | string | Parent cluster ID |
| `silo_id` | string | Silo ID |

**Returns:** List of summary strings

```cypher
MATCH (parent:Cluster {id: $cluster_id, silo_id: $silo_id})
MATCH (child:Cluster)-[:PART_OF]->(parent)
MATCH (f:Finding)-[:ABOUT]->(child)
WHERE f.silo_id = $silo_id
  AND (f.source = 'extraction' OR f.status = 'published')
RETURN f.summary AS summary
```

---

### `FETCH_COARSE_FINDINGS_FOR_SILO`

Fetch all coarse-level findings for a silo with their claims.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |
| `coarse_level` | int | Coarse level (typically 3) |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `finding_id` | string |
| `cluster_id` | string |
| `summary` | string |
| `claims_json` | string |
| `quality_score` | float |

```cypher
MATCH (f:Finding {scope: "cluster", silo_id: $silo_id})-[:ABOUT]->(c:Cluster)
WHERE c.level = $coarse_level
  AND (f.source = 'extraction' OR f.status = 'published')
RETURN f.id AS finding_id,
       c.id AS cluster_id,
       f.summary AS summary,
       f.claims AS claims_json,
       f.quality_score AS quality_score
ORDER BY f.quality_score DESC
```

---

### `FETCH_TOP_ENTITIES_BY_CITATION`

Top 20 entities by citation frequency across a silo.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows (max 20)
| Field | Type |
|-------|------|
| `node_id` | string |
| `content` | string |
| `cite_count` | int |

```cypher
MATCH (f:Finding {silo_id: $silo_id})-[:CITES]->(n)
WHERE (f.source = 'extraction' OR f.status = 'published')
  AND (n:Document OR n:Passage OR n:Claim)
WITH n, count(f) AS cite_count
ORDER BY cite_count DESC
LIMIT 20
RETURN n.id AS node_id, n.content AS content, cite_count
```

---

### `PASS_GET_BY_ID`

Fetch a `:Pass` node by id and org_id for org-isolated status reads.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `pass_id` | string | Pass ID |
| `org_id` | string | Organization ID |

**Returns:** Single row or null
| Field | Type |
|-------|------|
| `id` | string |
| `silo_id` | string |
| `org_id` | string |
| `status` | string |
| `started_at` | datetime |
| `finalized_at` | datetime |
| `cost_usd` | float |
| `visit_count` | int |

```cypher
MATCH (p:Pass {id: $pass_id, org_id: $org_id})
RETURN p.id AS id,
       p.silo_id AS silo_id,
       p.org_id AS org_id,
       p.status AS status,
       p.started_at AS started_at,
       p.finalized_at AS finalized_at,
       p.cost_usd AS cost_usd,
       p.visit_count AS visit_count
LIMIT 1
```

---

### `PASS_CHECK_CLAIMED`

Check if a cluster is already CLAIMED in this pass.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `pass_id` | string | Pass ID |
| `cluster_id` | string | Cluster ID |

**Returns:** Single row
| Field | Type |
|-------|------|
| `claimed` | boolean |

```cypher
MATCH (p:Pass {id: $pass_id})-[:CLAIMED]->(c:Cluster {id: $cluster_id})
RETURN count(*) > 0 AS claimed
```

---

### `GET_CLUSTER`

Retrieve a cluster by ID.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Cluster ID |
| `silo_id` | string | Silo ID |

**Returns:** Cluster node

```cypher
MATCH (c:Cluster {id: $id, silo_id: $silo_id})
RETURN c
```

---

### `GET_CLUSTER_MEMBERS`

Get all members of a cluster with weights.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `n` | node |
| `node_labels` | list[string] |
| `weight` | float |

```cypher
MATCH (n)-[r:BELONGS_TO]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
RETURN n, labels(n) as node_labels, r.weight as weight
ORDER BY r.weight DESC
```

---

### `GET_CLUSTER_MEMBER_IDS`

Get member IDs for a cluster (retrieval channel).

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |
| `limit` | int | Max results |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `node_id` | string |
| `silo_id` | string |
| `node_type` | string |
| `weight` | float |

```cypher
MATCH (n)-[r:BELONGS_TO]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
WHERE (n:Document OR n:Passage OR n:Claim)
  AND coalesce(n.stale, false) = false
  AND n.committed = true
RETURN n.id AS node_id, n.silo_id AS silo_id,
       toLower(head(labels(n))) AS node_type, r.weight AS weight
ORDER BY r.weight DESC
LIMIT $limit
```

---

### `FIND_ENTITY_BY_NAME`

Find entity by case-insensitive name match.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |
| `name` | string | Entity name |

**Returns:** Entity node

```cypher
MATCH (e:Entity {silo_id: $silo_id})
WHERE toLower(e.name) = toLower($name)
RETURN e
```

---

### `FIND_ENTITIES_BY_NAME_TOKENS`

Find entities by token matching.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |
| `tokens` | list[string] | Search tokens (lowercased) |
| `limit` | int | Max results |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `id` | string |
| `name` | string |
| `entity_type` | string |
| `description` | string |
| `importance` | float |

```cypher
MATCH (e:Entity {silo_id: $silo_id})
WHERE ANY(token IN $tokens WHERE toLower(e.name) CONTAINS token)
RETURN e.id AS id, e.name AS name, e.entity_type AS entity_type,
       e.description AS description, e.importance AS importance
ORDER BY coalesce(e.importance, 0) DESC
LIMIT $limit
```

---

### `ENTITY_NEIGHBORHOOD_NODES`

Traverse from entity to content nodes via Claims.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `entity_id` | string | Seed entity ID |
| `silo_id` | string | Silo ID |
| `limit` | int | Max results |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `node_id` | string |
| `silo_id` | string |
| `node_type` | string |
| `hop_distance` | int |

```cypher
MATCH (seed:Entity {id: $entity_id, silo_id: $silo_id})
OPTIONAL MATCH (seed)<-[:MENTIONS]-(c1:Claim)-[:EXTRACTED_FROM]->(direct)
WHERE (direct:Document OR direct:Passage OR direct:Claim)
  AND direct.silo_id = $silo_id
  AND coalesce(direct.stale, false) = false
  AND direct.committed = true
WITH seed, collect(DISTINCT {id: direct.id, silo_id: direct.silo_id,
     node_type: toLower(head(labels(direct))), dist: 0}) AS directs
OPTIONAL MATCH (seed)-[]-(e2:Entity {silo_id: $silo_id})<-[:MENTIONS]-(c2:Claim)-[:EXTRACTED_FROM]->(hop)
WHERE (hop:Document OR hop:Passage OR hop:Claim)
  AND hop.silo_id = $silo_id
  AND coalesce(hop.stale, false) = false
  AND hop.committed = true
WITH directs + collect(DISTINCT {id: hop.id, silo_id: hop.silo_id,
     node_type: toLower(head(labels(hop))), dist: 1}) AS all_nodes
UNWIND all_nodes AS n
RETURN DISTINCT n.id AS node_id, n.silo_id AS silo_id,
       n.node_type AS node_type, min(n.dist) AS hop_distance
LIMIT $limit
```

---

### `GET_SEED_HEAT_BATCH`

Batch read heat + cluster tier for PPR seed weighting.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `seed_ids` | list[string] | Node IDs |
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `node_id` | string |
| `heat` | float |
| `cluster_tier` | string |

```cypher
UNWIND $seed_ids AS sid
MATCH (n {id: sid, silo_id: $silo_id})
WHERE n.committed = true
OPTIONAL MATCH (n)-[:BELONGS_TO]->(c:Cluster {silo_id: $silo_id})
RETURN n.id AS node_id,
       coalesce(n.heat_score, 0.0) AS heat,
       c.tier AS cluster_tier
```

---

## Write Queries

### `UPSERT_CLAIM`

MERGE a `:Claim` node by ID.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `claim_id` | string | Claim ID |
| `silo_id` | string | Silo ID |
| `fingerprint` | string | sha256(s\|p\|o) |
| `subject` | string | Subject |
| `predicate` | string | Predicate |
| `object` | string | Object |
| `valid_from` | datetime | Temporal start |
| `valid_to` | datetime | Temporal end |
| `source_doc_id` | string | Source document |
| `source_passage_id` | string | Source passage |
| `confidence` | float | Extraction confidence |
| `created_at` | datetime | Creation time |

**Returns:** `id`

```cypher
MERGE (c:Claim {id: $claim_id, silo_id: $silo_id})
ON CREATE SET
    c.fingerprint = $fingerprint,
    c.subject = $subject,
    c.predicate = $predicate,
    c.object = $object,
    c.valid_from = $valid_from,
    c.valid_to = $valid_to,
    c.source_doc_id = $source_doc_id,
    c.source_passage_id = $source_passage_id,
    c.confidence = $confidence,
    c.created_at = $created_at,
    c.committed = true
RETURN c.id AS id
```

---

### `ATTACH_CLAIM_TO_PASSAGE`

Create `EXTRACTED_FROM` edge from Claim to Passage.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `passage_id` | string | Passage ID |
| `claim_id` | string | Claim ID |
| `silo_id` | string | Silo ID |

```cypher
MATCH (ps:Passage {id: $passage_id, silo_id: $silo_id})
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (ps)<-[:EXTRACTED_FROM]-(c)
```

---

### `ATTACH_CLAIM_TO_DOCUMENT`

Create `EXTRACTED_FROM` edge from Claim to Document.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `doc_id` | string | Document ID |
| `claim_id` | string | Claim ID |
| `silo_id` | string | Silo ID |

```cypher
MATCH (d:Document {id: $doc_id, silo_id: $silo_id})
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (d)<-[:EXTRACTED_FROM]-(c)
```

---

### `UPSERT_ENTITY_MENTION`

MERGE entity and create MENTIONS edge from Claim.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `entity_id` | string | Entity ID |
| `silo_id` | string | Silo ID |
| `name` | string | Entity name |
| `entity_type` | string | Entity type |
| `claim_id` | string | Claiming claim ID |
| `created_at` | datetime | Creation time |

```cypher
MERGE (e:Entity {id: $entity_id, silo_id: $silo_id})
ON CREATE SET
    e.name = $name,
    e.entity_type = $entity_type,
    e.created_at = $created_at
WITH e
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (c)-[:MENTIONS]->(e)
```

---

### `CREATE_CONTRADICTS_EDGE`

Create contradiction edge between Claims.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `claim_id_a` | string | First claim |
| `claim_id_b` | string | Second claim |
| `silo_id` | string | Silo ID |
| `edge_id` | string | Edge identifier |

```cypher
MATCH (a:Claim {id: $claim_id_a, silo_id: $silo_id})
MATCH (b:Claim {id: $claim_id_b, silo_id: $silo_id})
MERGE (a)-[r:CONTRADICTS {id: $edge_id}]->(b)
```

---

### `FINDING_MERGE_CLUSTER_SCOPE`

MERGE a cluster-scope `:Finding` and attach `ABOUT` edge.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Finding ID |
| `scope` | string | `"cluster"` |
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |
| `org_id` | string | Organization ID |
| `pass_id` | string | Pass ID |
| `version` | int | Version number |
| `status` | string | `"draft"` |
| `summary_json` | string | JSON summary |
| `claims_json` | string | JSON claims |
| `inferred_json` | string | JSON proposed edges |
| `member_fingerprint` | string | Member fingerprint |
| `quality_score` | float | Quality score |
| `visit_ref` | string | Redis key |
| `source` | string | `"custodian"` |
| `model` | string | Model name |
| `created_at` | string | ISO datetime |
| `updated_at` | string | ISO datetime |

**Returns:** `id`, `version`

```cypher
MERGE (f:Finding {scope: $scope, cluster_id: $cluster_id, silo_id: $silo_id})
ON CREATE SET
    f.id = $id,
    f.created_at = $created_at
SET f.org_id = $org_id,
    f.pass_id = $pass_id,
    f.version = $version,
    f.status = $status,
    f.summary = $summary_json,
    f.claims = $claims_json,
    f.inferred_relations = $inferred_json,
    f.member_fingerprint = $member_fingerprint,
    f.quality_score = $quality_score,
    f.visit_ref = $visit_ref,
    f.needs_refresh = false,
    f.source = $source,
    f.model = $model,
    f.updated_at = $updated_at
WITH f
MATCH (c:Cluster {id: $cluster_id})
MERGE (f)-[:ABOUT]->(c)
RETURN f.id AS id, f.version AS version
```

---

### `FINDING_MERGE_SILO_SCOPE`

MERGE a silo-scope `:Finding` and attach `SUMMARIZES` edge.

**Parameters:** Same as cluster-scope minus `cluster_id`.

**Returns:** `id`, `version`

```cypher
MERGE (f:Finding {scope: $scope, silo_id: $silo_id})
ON CREATE SET
    f.id = $id,
    f.created_at = $created_at,
    f.cluster_id = null
SET f.org_id = $org_id,
    f.pass_id = $pass_id,
    f.version = $version,
    f.status = $status,
    f.summary = $summary_json,
    f.claims = $claims_json,
    f.inferred_relations = $inferred_json,
    f.member_fingerprint = $member_fingerprint,
    f.quality_score = $quality_score,
    f.visit_ref = $visit_ref,
    f.needs_refresh = false,
    f.source = $source,
    f.model = $model,
    f.updated_at = $updated_at
WITH f
MATCH (s:Silo {id: $silo_id})
MERGE (f)-[:SUMMARIZES]->(s)
RETURN f.id AS id, f.version AS version
```

---

### `CITES_EDGE_CREATE`

Create citation edge from Finding to content node.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `finding_id` | string | Finding ID |
| `node_id` | string | Cited node ID |
| `kind` | string | `"primary"` or `"supporting"` |

**Returns:** `kind`

```cypher
MATCH (f:Finding {id: $finding_id})
MATCH (n {id: $node_id})
WHERE n:Document OR n:Passage OR n:Claim
MERGE (f)-[e:CITES {kind: $kind}]->(n)
RETURN e.kind AS kind
```

---

### `PASS_CREATE`

Create a new `:Pass` node.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Pass ID |
| `silo_id` | string | Silo ID |
| `org_id` | string | Organization ID |
| `status` | string | `"running"` |
| `started_at` | string | ISO datetime |

**Returns:** `id`

```cypher
CREATE (p:Pass {
    id: $id,
    silo_id: $silo_id,
    org_id: $org_id,
    status: $status,
    started_at: $started_at,
    finalized_at: null,
    cost_usd: 0.0,
    visit_count: 0
})
RETURN p.id AS id
```

---

### `PASS_CLAIMED_EDGE_MERGE`

MERGE the visit claim ledger edge.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `pass_id` | string | Pass ID |
| `cluster_id` | string | Cluster ID |
| `claimed_at` | string | ISO datetime |

**Returns:** `claimed_at`

```cypher
MATCH (p:Pass {id: $pass_id})
MATCH (c:Cluster {id: $cluster_id})
MERGE (p)-[e:CLAIMED]->(c)
ON CREATE SET e.claimed_at = $claimed_at
RETURN e.claimed_at AS claimed_at
```

---

### `PASS_FINALIZE`

Finalize a pass with terminal status.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `pass_id` | string | Pass ID |
| `status` | string | Terminal status |
| `finalized_at` | string | ISO datetime |
| `cost_usd` | float | Total cost |
| `visit_count` | int | Visit count |

**Returns:** `id`

```cypher
MATCH (p:Pass {id: $pass_id})
SET p.status = $status,
    p.finalized_at = $finalized_at,
    p.cost_usd = $cost_usd,
    p.visit_count = $visit_count
RETURN p.id AS id
```

---

### `CREATE_CLUSTER`

Create a new cluster.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Cluster ID |
| `silo_id` | string | Silo ID |
| `level` | int | Hierarchy level |
| `community_id` | int | Leiden community ID |
| `summary` | string | Cluster summary |
| `key_topics` | list[string] | Topic keywords |
| `node_count` | int | Member count |
| `created_at` | datetime | Creation time |
| `updated_at` | datetime | Update time |

**Returns:** Cluster node

```cypher
CREATE (c:Cluster {
    id: $id,
    silo_id: $silo_id,
    level: $level,
    community_id: $community_id,
    summary: $summary,
    key_topics: $key_topics,
    node_count: $node_count,
    created_at: $created_at,
    updated_at: $updated_at
})
RETURN c
```

---

### `CREATE_BELONGS_TO`

Create cluster membership edge.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `node_id` | string | Member node ID |
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |
| `weight` | float | Membership weight |
| `created_at` | datetime | Creation time |

**Returns:** Edge

```cypher
MATCH (n {id: $node_id})
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
WHERE n:Document OR n:Passage OR n:Claim OR n:Entity
CREATE (n)-[r:BELONGS_TO {weight: $weight, created_at: $created_at}]->(c)
RETURN r
```

---

### `CREATE_PART_OF`

Create cluster hierarchy edge.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `child_id` | string | Child cluster ID |
| `parent_id` | string | Parent cluster ID |
| `silo_id` | string | Silo ID |
| `created_at` | datetime | Creation time |

**Returns:** Edge

```cypher
MATCH (child:Cluster {id: $child_id, silo_id: $silo_id})
MATCH (parent:Cluster {id: $parent_id, silo_id: $silo_id})
CREATE (child)-[r:PART_OF {created_at: $created_at}]->(parent)
RETURN r
```

---

### `CREATE_ENTITY`

Create a new entity.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Entity ID |
| `silo_id` | string | Silo ID |
| `name` | string | Entity name |
| `entity_type` | string | Entity type |
| `description` | string | Description |
| `qualified_name` | string | Qualified name |
| `file_path` | string | Source file |
| `created_at` | datetime | Creation time |

**Returns:** Entity node

```cypher
CREATE (e:Entity {
    id: $id,
    silo_id: $silo_id,
    name: $name,
    entity_type: $entity_type,
    description: $description,
    qualified_name: $qualified_name,
    file_path: $file_path,
    created_at: $created_at
})
RETURN e
```

---

## Lifecycle Queries

### `FACT_MERGE`

MERGE a `:Fact` node by fingerprint (promotion target). **Phase 1 design.**

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `id` | string | Fact ID (uuid) |
| `silo_id` | string | Silo ID |
| `fingerprint` | string | sha256(subject_id\|predicate\|object) |
| `subject_id` | string | Subject entity ID |
| `predicate` | string | Predicate |
| `object_id` | string | Object entity ID (nullable) |
| `object_literal` | string | Object literal (nullable) |
| `confidence` | float | Aggregated confidence |
| `raw_confidence_max` | float | Max single-claim confidence |
| `source_count` | int | Contributing source count |
| `authoritative_count` | int | Authoritative source count |
| `promoted_via` | string | `R1`, `R2`, `R3`, `R4` |
| `promoted_at` | datetime | Promotion time |
| `updated_at` | datetime | Update time |

**Returns:** `id`, `source_count`

```cypher
MERGE (f:Fact {fingerprint: $fingerprint, silo_id: $silo_id})
ON CREATE SET
    f.id = $id,
    f.layer = 'knowledge',
    f.subject_id = $subject_id,
    f.predicate = $predicate,
    f.object_id = $object_id,
    f.object_literal = $object_literal,
    f.confidence = $confidence,
    f.raw_confidence_max = $raw_confidence_max,
    f.source_count = $source_count,
    f.authoritative_count = $authoritative_count,
    f.promoted_via = $promoted_via,
    f.promoted_at = $promoted_at,
    f.updated_at = $updated_at,
    f.superseded = false
ON MATCH SET
    f.confidence = $confidence,
    f.raw_confidence_max = CASE WHEN $raw_confidence_max > f.raw_confidence_max
                                THEN $raw_confidence_max ELSE f.raw_confidence_max END,
    f.source_count = $source_count,
    f.authoritative_count = $authoritative_count,
    f.updated_at = $updated_at
RETURN f.id AS id, f.source_count AS source_count
```

---

### `FACT_DERIVED_FROM`

Create `DERIVED_FROM` edge from Fact to source Passage.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `fact_id` | string | Fact ID |
| `passage_id` | string | Source passage ID |
| `silo_id` | string | Silo ID |
| `created_at` | datetime | Creation time |

```cypher
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
MATCH (p:Passage {id: $passage_id, silo_id: $silo_id})
MERGE (f)-[r:DERIVED_FROM]->(p)
ON CREATE SET r.created_at = $created_at
```

---

### `MARK_CLAIMS_PROMOTED`

Set `promoted_to_fact=true` on contributing Claims.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `claim_ids` | list[string] | Claim IDs |
| `silo_id` | string | Silo ID |

**Returns:** Count of updated claims

```cypher
UNWIND $claim_ids AS cid
MATCH (c:Claim {id: cid, silo_id: $silo_id})
SET c.promoted_to_fact = true
RETURN count(c) AS updated
```

---

### `FETCH_UNPROMOTED_CLAIMS`

Fetch Claims ready for promotion.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `id` | string |
| `fingerprint` | string |
| `subject` | string |
| `predicate` | string |
| `object` | string |
| `confidence` | float |
| `source_passage_id` | string |

```cypher
MATCH (c:Claim {silo_id: $silo_id})
WHERE c.committed = true
  AND coalesce(c.promoted_to_fact, false) = false
RETURN c.id AS id,
       c.fingerprint AS fingerprint,
       c.subject AS subject,
       c.predicate AS predicate,
       c.object AS object,
       c.confidence AS confidence,
       c.source_passage_id AS source_passage_id
```

---

### `DETECT_CONTRADICTION`

Find existing Fact with same (subject_id, predicate) but different object.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |
| `subject_id` | string | Subject entity ID |
| `predicate` | string | Predicate |
| `object_id` | string | New object ID |
| `object_literal` | string | New object literal |

**Returns:** Contradicting Fact if exists
| Field | Type |
|-------|------|
| `id` | string |
| `confidence` | float |
| `object_id` | string |
| `object_literal` | string |

```cypher
MATCH (f:Fact {silo_id: $silo_id, subject_id: $subject_id, predicate: $predicate})
WHERE f.superseded = false
  AND (f.object_id <> $object_id OR f.object_literal <> $object_literal)
RETURN f.id AS id,
       f.confidence AS confidence,
       f.object_id AS object_id,
       f.object_literal AS object_literal
```

---

### `CREATE_SUPERSEDES_EDGE`

Write SUPERSEDES edge for contradiction resolution.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `new_fact_id` | string | Superseding fact ID |
| `old_fact_id` | string | Superseded fact ID |
| `reason` | string | `"contradiction"` |
| `evidence_node_id` | string | Evidence node ID |
| `superseded_at` | datetime | When superseded |

```cypher
MATCH (new:Fact {id: $new_fact_id})
MATCH (old:Fact {id: $old_fact_id})
CREATE (new)-[:SUPERSEDES {
    reason: $reason,
    contradicting_evidence_node_id: $evidence_node_id,
    superseded_at: $superseded_at
}]->(old)
SET old.superseded = true
```

---

## Provenance Queries

### `TRACE_PROVENANCE`

Trace provenance chain back from a node.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `node_id` | string | Starting node ID |
| `silo_id` | string | Silo ID |
| `depth` | int | Max traversal depth |

**Returns:** Multiple rows (edges in chain)
| Field | Type |
|-------|------|
| `source_id` | string |
| `target_id` | string |
| `edge_type` | string |
| `hop` | int |

```cypher
MATCH path = (start {id: $node_id, silo_id: $silo_id})-[:DERIVED_FROM|CITES|PROMOTED_FROM*1..$depth]->(end)
UNWIND relationships(path) AS r
WITH startNode(r) AS s, endNode(r) AS e, type(r) AS t,
     length(shortestPath((start)-[:DERIVED_FROM|CITES|PROMOTED_FROM*]->(s))) AS hop
RETURN s.id AS source_id, e.id AS target_id, t AS edge_type, hop
ORDER BY hop
```

---

### `GET_FACT_SOURCES`

Get all source passages for a Fact.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `fact_id` | string | Fact ID |
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `passage_id` | string |
| `content` | string |

```cypher
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})-[:DERIVED_FROM]->(p:Passage)
RETURN p.id AS passage_id, p.content AS content
```

---

### `GET_SUPERSESSION_CHAIN`

Get the supersession chain for a Fact.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `fact_id` | string | Starting fact ID |
| `silo_id` | string | Silo ID |

**Returns:** Chain of superseded facts
| Field | Type |
|-------|------|
| `id` | string |
| `superseded` | boolean |
| `reason` | string |

```cypher
MATCH path = (start:Fact {id: $fact_id, silo_id: $silo_id})-[:SUPERSEDES*0..]->(old:Fact)
UNWIND nodes(path) AS n
WITH DISTINCT n
OPTIONAL MATCH (n)-[r:SUPERSEDES]->()
RETURN n.id AS id, n.superseded AS superseded, r.reason AS reason
ORDER BY n.updated_at DESC
```

---

## Batch Operations

### `BATCH_CREATE_BELONGS_TO`

Batch create cluster membership edges.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `cluster_id` | string | Cluster ID |
| `silo_id` | string | Silo ID |
| `node_ids` | list[string] | Member node IDs |
| `weight` | float | Membership weight |
| `created_at` | datetime | Creation time |

**Returns:** `created` count

```cypher
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
UNWIND $node_ids AS nid
MATCH (n {id: nid})
WHERE n:Document OR n:Passage OR n:Claim OR n:Entity
CREATE (n)-[:BELONGS_TO {weight: $weight, created_at: $created_at}]->(c)
RETURN count(*) as created
```

---

### `BATCH_UPDATE_NODE_IMPORTANCE`

Batch update PageRank importance scores.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `updates` | list[{node_id, rank}] | Update list |
| `silo_id` | string | Silo ID |

**Returns:** `updated` count

```cypher
UNWIND $updates AS u
MATCH (n {id: u.node_id, silo_id: $silo_id})
WHERE n:Document OR n:Passage OR n:Claim OR n:Entity
SET n.importance = u.rank
RETURN count(n) as updated
```

---

### `BATCH_FIND_OR_CREATE_ENTITIES`

Find or create entities in a single round trip.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `entities` | list[object] | Entity specs (name, name_lower, qualified_name, etc.) |
| `silo_id` | string | Silo ID |
| `created_at` | datetime | Creation time |

**Returns:** Multiple rows with `name` and `id`

```cypher
UNWIND $entities AS ent
OPTIONAL MATCH (existing:Entity {silo_id: $silo_id})
WHERE toLower(existing.name) = ent.name_lower
   OR (ent.qualified_name_lower IS NOT NULL
       AND toLower(existing.qualified_name) = ent.qualified_name_lower)
WITH ent, collect(existing)[0] AS hit
FOREACH (_ IN CASE WHEN hit IS NULL THEN [1] ELSE [] END |
    CREATE (n:Entity {
        id: ent.new_id,
        silo_id: $silo_id,
        name: ent.name,
        entity_type: ent.entity_type,
        description: ent.description,
        qualified_name: ent.qualified_name,
        file_path: ent.file_path,
        created_at: $created_at
    })
)
WITH ent, hit
OPTIONAL MATCH (created:Entity {id: ent.new_id, silo_id: $silo_id})
WITH ent, coalesce(hit, created) AS e
RETURN ent.name AS name, e.id AS id
```

---

## Graph Algorithms

### `RUN_LEIDEN`

Run Leiden community detection via Memgraph MAGE.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `gamma` | float | Resolution parameter |
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `node_id` | string |
| `community_id` | int |

```cypher
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND (node:Document OR node:Passage OR node:Claim OR node:Entity)
RETURN node.id AS node_id, community_id
```

---

### `RUN_PAGERANK`

Run PageRank via Memgraph MAGE.

**Parameters:**
| Name | Type | Description |
|------|------|-------------|
| `silo_id` | string | Silo ID |

**Returns:** Multiple rows
| Field | Type |
|-------|------|
| `node_id` | string |
| `rank` | float |

```cypher
CALL pagerank.get()
YIELD node, rank
WITH node, rank
WHERE (node:Document OR node:Passage OR node:Claim OR node:Entity)
  AND node.silo_id = $silo_id
RETURN node.id AS node_id, rank
```

---

## Health/Utility

### `HEALTH_CHECK`

Simple health check query.

**Parameters:** None

**Returns:** `health = 1`

```cypher
RETURN 1 as health
```
