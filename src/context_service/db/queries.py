"""Cypher query templates for Memgraph operations.

All queries use parameterized values for safety.
Queries are silo-scoped; Node/Entity records carry silo_id only (no tenant_id).

Phase-3 label scheme (O-30): content nodes are :Document, :Passage, :Claim.
:Entity is the pivot label. No :Node label in new code.
All retrieval-facing reads filter AND n.committed = true per O-75.
"""

from context_service.db.schema import (
    EDGE_EXTRACTED_FROM,
    EDGE_MENTIONS,
    LABEL_ENTITY,
    content_union_predicate,
)

# Entity queries

FIND_ENTITY_BY_NAME = """
MATCH (e:Entity {silo_id: $silo_id})
WHERE toLower(e.name) = toLower($name)
  AND NOT exists(e.tombstoned_at)
RETURN e
"""

CREATE_ENTITY = """
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
"""


def build_create_entity_relationship_query(rel_type: str) -> str:
    """Build a CREATE entity relationship query with a real edge label.

    The edge label comes from the closed :class:`RelationshipType` vocabulary.
    Domain-specific nuance is captured on edge properties:
    ``kind`` (free-form verb), ``directed``, ``confidence``, ``temporal``,
    and ``source_node_ids``.
    """
    return f"""
MATCH (a:Entity {{id: $source_id, silo_id: $silo_id}})
MATCH (b:Entity {{id: $target_id, silo_id: $silo_id}})
CREATE (a)-[r:{rel_type} {{
    kind: $kind,
    directed: $directed,
    confidence: $confidence,
    temporal: $temporal,
    source_node_ids: $source_node_ids,
    created_at: $created_at
}}]->(b)
RETURN r
"""


# Cluster CRUD queries
CREATE_CLUSTER = """
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
"""

GET_CLUSTER = """
MATCH (c:Cluster {id: $id, silo_id: $silo_id})
RETURN c
"""

LIST_CLUSTERS = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE ($level IS NULL OR c.level = $level)
RETURN c
ORDER BY c.node_count DESC
SKIP $offset
LIMIT $limit
"""

COUNT_CLUSTERS = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE ($level IS NULL OR c.level = $level)
RETURN count(c) as total
"""

DELETE_CLUSTERS = """
MATCH (c:Cluster {silo_id: $silo_id})
DETACH DELETE c
RETURN count(c) as deleted
"""

# Cluster membership queries
CREATE_MEMBER_OF = f"""
MATCH (n {{id: $node_id}})
MATCH (c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
WHERE {content_union_predicate("n")} OR n:{LABEL_ENTITY}
CREATE (n)-[r:MEMBER_OF {{weight: $weight, created_at: $created_at}}]->(c)
RETURN r
"""

CREATE_PART_OF = """
MATCH (child:Cluster {id: $child_id, silo_id: $silo_id})
MATCH (parent:Cluster {id: $parent_id, silo_id: $silo_id})
CREATE (child)-[r:PART_OF {created_at: $created_at}]->(parent)
RETURN r
"""

# R-006: collapse N per-pair CREATE_PART_OF calls into one UNWIND round-trip.
# Each entry in $pairs must carry {child_id, parent_id}.
BATCH_CREATE_PART_OF = """
UNWIND $pairs AS p
MATCH (child:Cluster {id: p.child_id, silo_id: $silo_id})
MATCH (parent:Cluster {id: p.parent_id, silo_id: $silo_id})
MERGE (child)-[:PART_OF {created_at: $created_at}]->(parent)
RETURN count(*) AS created
"""

GET_CLUSTER_MEMBERS = """
MATCH (n)-[r:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
RETURN n, labels(n) as node_labels, r.weight as weight
ORDER BY r.weight DESC
"""

GET_NODE_CLUSTERS = """
MATCH (n {id: $node_id})-[r:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
RETURN c, r.weight as weight
ORDER BY c.level ASC
"""

GET_CLUSTER_PARENT = """
MATCH (child:Cluster {id: $child_id, silo_id: $silo_id})-[:PART_OF]->(parent:Cluster)
RETURN parent.id AS parent_id
"""

# Leiden community detection via Memgraph MAGE (igraph implementation).
#
# We use `igraphalg.community_leiden` (igraph's Leiden) instead of MAGE's
# native `leiden_community_detection.get` because the native implementation
# raises "No communities detected" on our graph at every resolution value.
# igraph Leiden handles the same graph fine and is algorithmically the same.
#
# Signature:
#   igraphalg.community_leiden(
#     objective_function :: STRING = "CPM",
#     weights :: STRING? = null,
#     resolution_parameter :: FLOAT = 1.0,
#     beta :: FLOAT = 0.01,
#     initial_membership :: LIST? = null,
#     n_iterations :: INTEGER = 2,
#     node_weights :: LIST? = null
#   ) :: (community_id :: INTEGER, node :: NODE)
#
# We pass CPM + varying resolution_parameter as our "gamma" to get the
# hierarchical levels. Silo filtering is done after detection by only
# processing assignments for nodes belonging to this silo.
RUN_LEIDEN = f"""
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND ({content_union_predicate("node")} OR node:{LABEL_ENTITY})
RETURN node.id AS node_id, community_id
"""

# PageRank via Memgraph MAGE
# Note: PageRank runs on the whole graph; filter results by silo. Importance
# applies to Document, Passage, Claim, and Entity nodes — all participate in
# clustering and retrieval ranking.
RUN_PAGERANK = f"""
CALL pagerank.get()
YIELD node, rank
WITH node, rank
WHERE ({content_union_predicate("node")} OR node:{LABEL_ENTITY})
  AND node.silo_id = $silo_id
RETURN node.id AS node_id, rank
"""

UPDATE_CLUSTER_SUMMARY = """
MATCH (c:Cluster {id: $id, silo_id: $silo_id})
SET c.summary = $summary, c.key_topics = $key_topics, c.updated_at = $updated_at
RETURN c
"""

# Batch operations
BATCH_CREATE_MEMBER_OF = f"""
MATCH (c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
UNWIND $node_ids AS nid
MATCH (n {{id: nid}})
WHERE {content_union_predicate("n")} OR n:{LABEL_ENTITY}
CREATE (n)-[:MEMBER_OF {{weight: $weight, created_at: $created_at}}]->(c)
RETURN count(*) as created
"""

BATCH_UPDATE_NODE_IMPORTANCE = f"""
UNWIND $updates AS u
MATCH (n {{id: u.node_id, silo_id: $silo_id}})
WHERE {content_union_predicate("n")} OR n:{LABEL_ENTITY}
SET n.importance = u.rank
RETURN count(n) as updated
"""

# --- Phase-3 §3.3 Claim write-path queries ---
# NOTE: BATCH_CREATE_EXTRACTED_FROM (legacy Entity->Passage attribution) was
# removed in phase-3.6. Per O-30, EXTRACTED_FROM is Claim->Passage only; the
# legacy query wrote a spec-illegal edge shape. The Claim-mediated path lives
# in ATTACH_CLAIM_TO_PASSAGE + UPSERT_ENTITY_MENTION below.

UPSERT_CLAIM = """
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
"""

ATTACH_CLAIM_TO_PASSAGE = """
MATCH (ps:Passage {id: $passage_id, silo_id: $silo_id})
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (ps)<-[:EXTRACTED_FROM]-(c)
"""

ATTACH_CLAIM_TO_DOCUMENT = """
MATCH (d:Document {id: $doc_id, silo_id: $silo_id})
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (d)<-[:EXTRACTED_FROM]-(c)
"""

UPSERT_ENTITY_MENTION = """
MERGE (e:Entity {id: $entity_id, silo_id: $silo_id})
ON CREATE SET
    e.name = $name,
    e.entity_type = $entity_type,
    e.created_at = $created_at
WITH e
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (c)-[:MENTIONS]->(e)
"""

ATTACH_CLAIM_REFERENCES_DOC = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MATCH (refd:Document {id: $ref_doc_id, silo_id: $silo_id})
MERGE (c)-[:REFERENCES]->(refd)
"""

PROMOTE_CLAIM_TO_FACT = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
WHERE NOT exists((c)<-[:PROMOTED_FROM]-(:Fact))
CREATE (f:Fact {
    id: $fact_id,
    silo_id: c.silo_id,
    content: c.content,
    confidence: c.confidence,
    fingerprint: c.fingerprint,
    source_tier: c.source_tier,
    promoted_at: datetime(),
    promotion_rule: $rule,
    valid_from: datetime(),
    created_at: datetime()
})
CREATE (f)-[:PROMOTED_FROM]->(c)
RETURN f.id AS fact_id, properties(f) AS props
"""

CREATE_CONTRADICTS_EDGE = """
MATCH (a:Claim {id: $claim_id_a, silo_id: $silo_id})
MATCH (b:Claim {id: $claim_id_b, silo_id: $silo_id})
MERGE (a)-[r:CONTRADICTS {id: $edge_id}]->(b)
"""

# Causal edge: written between any two silo nodes (Claims, Facts, Beliefs, etc.)
# Parameters: source_id, target_id, silo_id, confidence (float), mechanism (str|null),
#             extracted_from (str — source doc or claim id).
CREATE_CAUSES_EDGE = """
MATCH (a {id: $source_id, silo_id: $silo_id})
MATCH (b {id: $target_id, silo_id: $silo_id})
CREATE (a)-[:CAUSES {confidence: $confidence, mechanism: $mechanism, created_at: datetime(), extracted_from: $extracted_from}]->(b)
"""

# Corroboration edge: a supports / confirms b.
# Parameters: source_id, target_id, silo_id, strength (float), extracted_from (str).
CREATE_CORROBORATES_EDGE = """
MATCH (a {id: $source_id, silo_id: $silo_id})
MATCH (b {id: $target_id, silo_id: $silo_id})
CREATE (a)-[:CORROBORATES {strength: $strength, created_at: datetime(), extracted_from: $extracted_from}]->(b)
"""


def build_batch_entity_rel_query(rel_type: str) -> str:
    """Build a batch CREATE entity relationship query with a real edge label.

    The edge label comes from the closed :class:`RelationshipType` vocabulary.
    Each row in ``$rels`` must carry ``source_id``, ``target_id``, ``kind``,
    ``directed``, ``confidence``, ``temporal``, ``source_node_ids``, and
    ``created_at``.
    """
    return f"""
UNWIND $rels AS r
MATCH (a:Entity {{id: r.source_id, silo_id: $silo_id}})
MATCH (b:Entity {{id: r.target_id, silo_id: $silo_id}})
CREATE (a)-[:{rel_type} {{
    kind: r.kind,
    directed: r.directed,
    confidence: r.confidence,
    temporal: r.temporal,
    source_node_ids: r.source_node_ids,
    created_at: r.created_at
}}]->(b)
RETURN count(*) as created
"""


# Entity retrieval channel queries

FIND_ENTITIES_BY_NAME_TOKENS = """
MATCH (e:Entity {silo_id: $silo_id})
WHERE ANY(token IN $tokens WHERE toLower(e.name) CONTAINS token)
  AND NOT exists(e.tombstoned_at)
RETURN e.id AS id, e.name AS name, e.entity_type AS entity_type,
       e.description AS description, e.importance AS importance
ORDER BY coalesce(e.importance, 0) DESC
LIMIT $limit
"""

# Entity-to-content traversal (O-30 edge directions):
#   Entity <-[:MENTIONS]- Claim -[:EXTRACTED_FROM]-> Passage/Document
# i.e. (seed entity) <- MENTIONS - (claim) - EXTRACTED_FROM -> (content node)
ENTITY_NEIGHBORHOOD_NODES = f"""
MATCH (seed:{LABEL_ENTITY} {{id: $entity_id, silo_id: $silo_id}})
OPTIONAL MATCH (seed)<-[:{EDGE_MENTIONS}]-(c1:Claim)-[:{EDGE_EXTRACTED_FROM}]->(direct)
WHERE {content_union_predicate("direct")} AND direct.silo_id = $silo_id
  AND coalesce(direct.stale, false) = false AND direct.committed = true
WITH seed, collect(DISTINCT {{id: direct.id, silo_id: direct.silo_id, node_type: toLower(head(labels(direct))), dist: 0}}) AS directs
OPTIONAL MATCH (seed)-[]-(e2:{LABEL_ENTITY} {{silo_id: $silo_id}})<-[:{EDGE_MENTIONS}]-(c2:Claim)-[:{EDGE_EXTRACTED_FROM}]->(hop)
WHERE {content_union_predicate("hop")} AND hop.silo_id = $silo_id
  AND coalesce(hop.stale, false) = false AND hop.committed = true
WITH directs + collect(DISTINCT {{id: hop.id, silo_id: hop.silo_id, node_type: toLower(head(labels(hop))), dist: 1}}) AS all_nodes
UNWIND all_nodes AS n
RETURN DISTINCT n.id AS node_id, n.silo_id AS silo_id, n.node_type AS node_type, min(n.dist) AS hop_distance
LIMIT $limit
"""

# Cluster retrieval channel queries

GET_CLUSTER_MEMBER_IDS = f"""
MATCH (n)-[r:MEMBER_OF]->(c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
WHERE {content_union_predicate("n")} AND coalesce(n.stale, false) = false AND n.committed = true
RETURN n.id AS node_id, n.silo_id AS silo_id, toLower(head(labels(n))) AS node_type, r.weight AS weight
ORDER BY r.weight DESC
LIMIT $limit
"""

SEARCH_CLUSTERS_BY_KEYWORDS = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE c.summary IS NOT NULL
  AND ($level IS NULL OR c.level = $level)
  AND ANY(token IN $tokens WHERE toLower(c.summary) CONTAINS token)
RETURN c.id AS id, c.level AS level, c.summary AS summary, c.node_count AS node_count
ORDER BY c.node_count DESC
LIMIT $limit
"""

# Entity queries with qualified_name support
FIND_ENTITY_BY_QUALIFIED_NAME = """
MATCH (e:Entity {silo_id: $silo_id})
WHERE (toLower(e.name) = toLower($name)
   OR ($qualified_name IS NOT NULL AND toLower(e.qualified_name) = toLower($qualified_name)))
  AND NOT exists(e.tombstoned_at)
RETURN e
"""

# Batch find-or-create entities in a single round trip.
#
# Each row in $entities carries: name, name_lower, qualified_name,
# qualified_name_lower, entity_type, description, file_path, new_id.
# Dedup semantics match FIND_ENTITY_BY_QUALIFIED_NAME (case-insensitive name
# OR qualified_name match within the silo). When no existing match is
# found, a new :Entity is created using new_id. Returns one row per input
# entity: {name, id} so the caller can build a name -> id map.
BATCH_FIND_OR_CREATE_ENTITIES = """
UNWIND $entities AS ent
OPTIONAL MATCH (existing:Entity {silo_id: $silo_id})
WHERE toLower(existing.name) = ent.name_lower
   OR (
       ent.qualified_name_lower IS NOT NULL
       AND toLower(existing.qualified_name) = ent.qualified_name_lower
   )
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
"""

# Per-seed heat + cluster tier batch read for PPR restart-vector weighting
# (phase-5.2). Returns heat_score (nullable — 0.0 if unset) and the parent
# Cluster.tier (HOT/WARM/COLD/null) so the walker can apply a tier-based
# fallback when a seed has no heat yet (cold-start, O-61).
GET_SEED_HEAT_BATCH = """
UNWIND $seed_ids AS sid
MATCH (n {id: sid, silo_id: $silo_id})
WHERE n.committed = true
  AND NOT exists(n.tombstoned_at)
OPTIONAL MATCH (n)-[:MEMBER_OF]->(c:Cluster {silo_id: $silo_id})
RETURN n.id AS node_id,
       coalesce(n.heat_score, 0.0) AS heat,
       c.tier AS cluster_tier
"""

# Health check query
HEALTH_CHECK = "RETURN 1 as health"

# Meta-memory: provenance chain query
# Traverses DERIVED_FROM / PROMOTED_FROM / SYNTHESIZED_FROM edges from a
# given node back to its Memory-layer sources (leaves with no outbound edges).
PROVENANCE_CHAIN = """
MATCH path = (start {id: $node_id, silo_id: $silo_id})-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM|REFERENCES*1..10]->(source)
WITH path, nodes(path) AS ns, relationships(path) AS rs
UNWIND range(0, size(ns) - 1) AS i
WITH
    ns[i].id AS node_id,
    labels(ns[i])[0] AS layer,
    CASE WHEN i < size(rs) THEN type(rs[i]) ELSE null END AS relationship,
    coalesce(ns[i].confidence, 1.0) AS confidence,
    length(path) AS depth
RETURN DISTINCT node_id, layer, relationship, confidence
ORDER BY depth
"""

# Leaf sources: nodes in the provenance chain with no further outbound edges
PROVENANCE_ROOT_SOURCES = """
MATCH path = (start {id: $node_id, silo_id: $silo_id})-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM|REFERENCES*1..10]->(source)
WHERE NOT (source)-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM|REFERENCES]->()
RETURN DISTINCT
    source.id AS node_id,
    labels(source)[0] AS layer,
    source.content AS content,
    coalesce(source.confidence, 1.0) AS confidence
"""

# Meta-memory: belief history via SUPERSEDES chain
# Walks backward through SUPERSEDES edges to reconstruct the evolution of a belief.
BELIEF_HISTORY_BY_NODE = """
MATCH path = (current {id: $node_id, silo_id: $silo_id})<-[:SUPERSEDES*0..20]-(ancestor)
WITH ancestor, length(path) AS depth
RETURN
    ancestor.id AS node_id,
    ancestor.content AS content,
    ancestor.valid_from AS valid_from,
    ancestor.valid_to AS valid_to,
    ancestor.confidence AS confidence,
    ancestor.supersession_reason AS supersession_reason
ORDER BY depth DESC
"""

# Meta-memory: reflections about a node
# Returns MetaObservations linked via ABOUT edge to the target node.
GET_REFLECTIONS_FOR_NODE = """
MATCH (obs:MetaObservation)-[:ABOUT]->(n {id: $node_id, silo_id: $silo_id})
WHERE obs.silo_id = $silo_id AND NOT exists(obs.tombstoned_at)
RETURN
    obs.id AS node_id,
    obs.content AS content,
    obs.observation_type AS observation_type,
    obs.confidence AS confidence,
    obs.agent_id AS agent_id,
    obs.created_at AS created_at
ORDER BY obs.created_at DESC
"""

BELIEF_HISTORY_CURRENT = """
MATCH (n {id: $node_id, silo_id: $silo_id})
OPTIONAL MATCH (n)-[:SUPERSEDES]->(next)
RETURN
    n.id AS node_id,
    n.content AS content,
    n.valid_from AS valid_from,
    n.valid_to AS valid_to,
    n.confidence AS confidence,
    next.id AS superseded_by,
    n.supersession_reason AS supersession_reason
"""

BELIEF_HISTORY_BY_SUBJECT = """
MATCH (n {silo_id: $silo_id})
WHERE (toLower(n.content) CONTAINS toLower($subject)
   OR ($subject IS NOT NULL AND n.subject IS NOT NULL AND toLower(n.subject) CONTAINS toLower($subject)))
  AND NOT exists(n.tombstoned_at)
WITH n
ORDER BY coalesce(n.valid_from, 0) ASC
RETURN
    n.id AS node_id,
    n.content AS content,
    n.valid_from AS valid_from,
    n.valid_to AS valid_to,
    n.confidence AS confidence,
    n.supersession_reason AS supersession_reason
LIMIT 50
"""

# ---------------------------------------------------------------------------
# Batch claim write-path queries (asset layer — R-003/F-016)
#
# The MCP service layer uses single-row per-claim writes (compatible with
# synchronous tool calls). The extraction asset uses these UNWIND variants to
# collapse N×4 RTTs to exactly 4 per batch.
# ---------------------------------------------------------------------------

BATCH_UPSERT_CLAIMS = """
UNWIND $claims AS c
MERGE (n:Claim {id: c.claim_id, silo_id: $silo_id})
ON CREATE SET
    n.fingerprint = c.fingerprint,
    n.subject = c.subject,
    n.predicate = c.predicate,
    n.object = c.object,
    n.valid_from = c.valid_from,
    n.valid_to = c.valid_to,
    n.source_doc_id = c.source_doc_id,
    n.source_passage_id = c.source_passage_id,
    n.confidence = c.confidence,
    n.created_at = c.created_at,
    n.committed = true
RETURN n.id AS id
"""

BATCH_ATTACH_CLAIMS_TO_DOCUMENT = """
UNWIND $rows AS r
MATCH (d:Document {id: r.doc_id, silo_id: $silo_id})
MATCH (c:Claim {id: r.claim_id, silo_id: $silo_id})
MERGE (d)<-[:EXTRACTED_FROM]-(c)
RETURN count(*) AS attached
"""

BATCH_UPSERT_ENTITY_MENTIONS = """
UNWIND $rows AS r
MERGE (e:Entity {id: r.entity_id, silo_id: $silo_id})
ON CREATE SET
    e.name = r.name,
    e.entity_type = r.entity_type,
    e.created_at = r.created_at
WITH e, r
MATCH (c:Claim {id: r.claim_id, silo_id: $silo_id})
MERGE (c)-[:MENTIONS]->(e)
RETURN count(*) AS upserted
"""

BATCH_ATTACH_CLAIM_REFERENCES = """
UNWIND $rows AS r
MATCH (c:Claim {id: r.claim_id, silo_id: $silo_id})
MATCH (d:Document {id: r.ref_doc_id, silo_id: $silo_id})
MERGE (c)-[:REFERENCES]->(d)
RETURN count(*) AS attached
"""


# --- Temporal query (time-travel) ---

TEMPORAL_QUERY = (
    "MATCH (n) "
    "WHERE n.silo_id = $silo_id "
    "  AND ($type_filter IS NULL OR any(label IN labels(n) WHERE label = $type_filter)) "
    "  AND n.valid_from <= $as_of "
    "  AND (n.valid_to IS NULL OR n.valid_to > $as_of) "
    "  AND n.content IS NOT NULL "
    "  AND NOT exists(n.tombstoned_at) "
    "RETURN n.id AS id, n.content AS content, labels(n) AS labels, "
    "       n.confidence AS confidence, n.valid_from AS valid_from, "
    "       n.valid_to AS valid_to, n.created_at AS created_at "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)

# --- Supersession chain traversal (belief history) ---

# ---------------------------------------------------------------------------
# Session compaction: ReasoningChain -> Event (Memory layer trace)
# ---------------------------------------------------------------------------

CREATE_REASONING_TRACE_EVENT = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MERGE (e:Event {id: $event_id, silo_id: $silo_id})
ON CREATE SET
    e.event_type = "reasoning_trace",
    e.content = $content,
    e.agent_id = $agent_id,
    e.created_at = $created_at,
    e.source_chain_id = $chain_id,
    e.step_count = $step_count,
    e.outcome = $outcome,
    e.summarization_pending = $summarization_pending
MERGE (e)-[:DERIVED_FROM]->(chain)
RETURN e.id AS event_id
"""

TOMBSTONE_REASONING_CHAIN = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
SET chain.compacted = true,
    chain.compacted_at = $compacted_at,
    chain.compact_event_id = $event_id
RETURN chain.id AS chain_id
"""

GET_REASONING_CHAIN_FOR_COMPACTION = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
RETURN
    chain.id AS id,
    chain.steps AS steps,
    chain.compact_summary AS compact_summary,
    chain.produced_by_agent_id AS agent_id,
    chain.tier AS tier,
    chain.status AS status,
    coalesce(chain.compacted, false) AS compacted
"""

GET_COMPACTABLE_CHAINS = """
MATCH (chain:ReasoningChain {silo_id: $silo_id})
WHERE coalesce(chain.compacted, false) = false
  AND chain.status IN $statuses
RETURN chain.id AS id, chain.status AS status
ORDER BY chain.created_at ASC
LIMIT $limit
"""

# --- Supersession chain traversal (belief history) ---

# ---------------------------------------------------------------------------
# Belief synthesis queries (Wisdom layer)
# ---------------------------------------------------------------------------

# Fetch all :Fact nodes that are members of a given cluster (via MEMBER_OF).
# Returns fact_id, content, confidence, and valid_from for each fact so the
# synthesis function can build the LLM prompt without a second round-trip.
GET_FACTS_IN_CLUSTER = """
MATCH (f:Fact)-[:MEMBER_OF]->(c:Cluster {id: $cluster_id, silo_id: $silo_id})
RETURN f.id AS fact_id, f.content AS content,
       coalesce(f.confidence, 1.0) AS confidence,
       f.valid_from AS valid_from
ORDER BY coalesce(f.confidence, 1.0) DESC
"""

# Create a :Belief node and attach SYNTHESIZED_FROM edges to all source facts
# in a single write.  $fact_ids is a list of fact id strings.
CREATE_BELIEF_FROM_FACTS = """
MERGE (b:Belief {id: $belief_id, silo_id: $silo_id})
ON CREATE SET
    b.content = $content,
    b.confidence = $confidence,
    b.evidence_count = $evidence_count,
    b.created_at = $created_at,
    b.valid_from = $valid_from,
    b.valid_to = null
WITH b
UNWIND $fact_ids AS fid
MATCH (f:Fact {id: fid, silo_id: $silo_id})
MERGE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN b.id AS belief_id, count(f) AS edges_created
"""

# Check whether a :Belief already exists whose content covers the subject
# (case-insensitive substring match).  Used before synthesis to skip
# redundant work.
CHECK_BELIEF_COVERAGE = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE toLower(b.content) CONTAINS toLower($subject)
  AND (b.valid_to IS NULL OR b.valid_to > $as_of)
  AND NOT exists(b.tombstoned_at)
RETURN b.id AS belief_id, b.content AS content, b.confidence AS confidence
LIMIT 1
"""

# Store the cluster centroid embedding on a :Belief node.
# Parameters: belief_id, silo_id, centroid_embedding (list[float]),
#             last_revision_check (ISO datetime str), revision_count (int).
UPDATE_BELIEF_CENTROID = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.centroid_embedding = $centroid_embedding,
    b.last_revision_check = $last_revision_check,
    b.revision_count = $revision_count,
    b.wisdom_status = coalesce(b.wisdom_status, 'active')
RETURN b.id AS belief_id
"""

# Create a :SUPERSEDES edge from a new :Belief to the one it replaces.
# Parameters: new_belief_id, old_belief_id, silo_id, reason (str),
#             created_at (ISO datetime str).
CREATE_BELIEF_SUPERSEDES = """
MATCH (newer:Belief {id: $new_belief_id, silo_id: $silo_id})
MATCH (older:Belief {id: $old_belief_id, silo_id: $silo_id})
MERGE (newer)-[r:SUPERSEDES {
    reason: $reason,
    created_at: $created_at
}]->(older)
RETURN r.reason AS reason
"""

# Mark a :Belief as stale after it has been superseded.
# Parameters: belief_id, silo_id, valid_to (ISO datetime str).
MARK_BELIEF_STALE = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.wisdom_status = 'stale',
    b.valid_to = $valid_to
RETURN b.id AS belief_id
"""

# ---------------------------------------------------------------------------
# Pattern queries (Wisdom layer)
# ---------------------------------------------------------------------------

# Create a :Pattern node and attach OBSERVED_IN edges to each observed node.
# $observed_node_ids is a list of node id strings (Fact, Belief, or Event).
CREATE_PATTERN = """
MERGE (p:Pattern {id: $pattern_id, silo_id: $silo_id})
ON CREATE SET
    p.pattern_type = $pattern_type,
    p.description = $description,
    p.frequency = $frequency,
    p.confidence = $confidence,
    p.first_observed = $first_observed,
    p.last_observed = $last_observed,
    p.created_at = $created_at
WITH p
UNWIND $observed_node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
MERGE (p)-[:OBSERVED_IN]->(n)
RETURN p.id AS pattern_id, count(n) AS edges_created
"""

# Increment frequency and update last_observed timestamp.
UPDATE_PATTERN_FREQUENCY = """
MATCH (p:Pattern {id: $pattern_id, silo_id: $silo_id})
SET p.frequency = p.frequency + 1,
    p.last_observed = $last_observed
RETURN p.id AS pattern_id, p.frequency AS frequency
"""

# Look up an existing pattern by type and subject description substring.
GET_PATTERN_BY_TYPE_AND_SUBJECT = """
MATCH (p:Pattern {silo_id: $silo_id, pattern_type: $pattern_type})
WHERE toLower(p.description) CONTAINS toLower($subject)
  AND (p.valid_to IS NULL OR p.valid_to > $as_of)
  AND NOT exists(p.tombstoned_at)
RETURN p.id AS pattern_id, p.description AS description,
       p.frequency AS frequency, p.confidence AS confidence,
       p.first_observed AS first_observed, p.last_observed AS last_observed
LIMIT 1
"""

# Detect temporal correlations: pairs of :Fact nodes in the same silo whose
# valid_from timestamps fall within $window_seconds of each other.  Returns
# up to $limit distinct unordered pairs so the caller can decide which to
# materialise as a :Pattern.
DETECT_TEMPORAL_CORRELATIONS = """
MATCH (a:Fact {silo_id: $silo_id}), (b:Fact {silo_id: $silo_id})
WHERE id(a) < id(b)
  AND a.valid_from IS NOT NULL
  AND b.valid_from IS NOT NULL
  AND abs(duration.inSeconds(a.valid_from, b.valid_from)) <= $window_seconds
RETURN a.id AS fact_id_a, b.id AS fact_id_b,
       a.content AS content_a, b.content AS content_b,
       a.valid_from AS valid_from_a, b.valid_from AS valid_from_b
ORDER BY a.valid_from DESC
LIMIT $limit
"""

GET_SUPERSESSION_CHAIN = (
    "MATCH (start {id: $start_id, silo_id: $silo_id}) "
    "OPTIONAL MATCH path = (start)-[:SUPERSEDES*0..20]->(related) "
    "WHERE ALL(x IN nodes(path) WHERE x.silo_id = $silo_id) "
    "WITH collect(DISTINCT related) + [start] AS all_nodes "
    "UNWIND all_nodes AS n "
    "WITH DISTINCT n "
    "OPTIONAL MATCH (n)-[:SUPERSEDES]->(superseded_by_node) "
    "RETURN n.id AS id, n.content AS content, "
    "       n.confidence AS confidence, "
    "       n.valid_from AS valid_from, n.valid_to AS valid_to, "
    "       superseded_by_node.id AS superseded_by "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)
