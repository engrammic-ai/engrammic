"""Cypher query templates for Memgraph operations.

All queries use parameterized values for safety.
Queries are silo-scoped; Node/Entity records carry silo_id only (no tenant_id).

CITE v2 label scheme (5 nodes, 6 edges):
  :Memory     — raw observations (was: Document, Passage, Utterance, Event, Observation)
  :Claim      — evidence-backed assertions
  :Fact       — SAGE-promoted claims
  :Belief     — SAGE-synthesized, agent-accepted
  :Commitment — agent decisions
All retrieval-facing reads filter AND n.committed = true per O-75.

Deprecated labels (kept as comments for migration reference):
  :Document, :Passage, :Entity, :Cluster, :ProposedBelief, :Pattern
Deprecated edges: EXTRACTED_FROM, MENTIONS, REFERENCES, MEMBER_OF
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from context_service.db.schema import (
    content_union_predicate,
)

if TYPE_CHECKING:
    from context_service.extraction.models import RelationshipType

# Entity queries


# DEPRECATED (CITE v2): Entity-to-entity relationship queries are removed.
# :Entity nodes and their typed relationship edges are no longer part of the
# v2 schema. Use ABOUT edges on Claim nodes to express entity references.
def build_create_entity_relationship_query(rel_type: RelationshipType) -> str:
    """Build a CREATE entity relationship query with a real edge label.

    DEPRECATED (CITE v2): Entity-to-entity edges are removed in v2.
    Kept for backward compatibility until all callers are updated.
    """
    label = rel_type.value  # guaranteed member of the closed enum
    return f"""
MATCH (a:Entity {{id: $source_id, silo_id: $silo_id}})
MATCH (b:Entity {{id: $target_id, silo_id: $silo_id}})
CREATE (a)-[r:{label} {{
    kind: $kind,
    directed: $directed,
    confidence: $confidence,
    temporal: $temporal,
    source_node_ids: $source_node_ids,
    created_at: $created_at
}}]->(b)
RETURN r
"""


# ---------------------------------------------------------------------------
# Phase 6 recall and cycle detection queries
# ---------------------------------------------------------------------------

# Get neighbors of a node for graph traversal (RECALL transaction).
# Returns neighbor id, edge type, direction, and properties.
# Excludes already-visited nodes and inactive neighbors.
TRAVERSE_NEIGHBORS = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[e]-(neighbor)
WHERE neighbor.silo_id = $silo_id
  AND neighbor.properties.state = 'ACTIVE'
  AND NOT neighbor.id IN $visited
RETURN neighbor.id AS id,
       type(e) AS edge_type,
       CASE WHEN startNode(e) = n THEN 'outgoing' ELSE 'incoming' END AS direction,
       neighbor.properties AS properties
LIMIT $limit
"""

# Check if adding a SUPERSEDES edge from source to target would create a cycle.
# A cycle exists when target can already reach source via SUPERSEDES.
CHECK_CYCLE_PATH = """
MATCH path = (source {id: $source_id, silo_id: $silo_id})-[:SUPERSEDES*1..10]->(target {id: $target_id, silo_id: $silo_id})
RETURN count(path) > 0 AS would_cycle
"""

# Get full node details for recall filtering (RECALL transaction).
# Returns all fields needed for result ranking and filtering.
GET_NODE_FOR_RECALL = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.id AS id,
       n.properties.content AS content,
       n.properties.layer AS layer,
       n.properties.state AS state,
       n.properties.confidence AS confidence,
       n.properties.corroboration_count AS corroboration_count,
       n.properties.synthesis_state AS synthesis_state,
       n.properties.created_at AS created_at,
       n.properties.valid_to AS valid_to,
       n.properties AS properties
"""

# Batched version of GET_NODE_FOR_RECALL for performance.
# Fetches multiple nodes in a single query.
GET_NODES_FOR_RECALL_BATCH = """
MATCH (n {silo_id: $silo_id})
WHERE n.id IN $node_ids
RETURN n.id AS id,
       n.properties.content AS content,
       n.properties.layer AS layer,
       n.properties.state AS state,
       n.properties.confidence AS confidence,
       n.properties.corroboration_count AS corroboration_count,
       n.properties.synthesis_state AS synthesis_state,
       n.properties.created_at AS created_at,
       n.properties.valid_to AS valid_to,
       coalesce(n.heat_score, 0.0) AS heat_score,
       n.properties AS properties
"""

# DEPRECATED (CITE v2): Clustering via :Cluster nodes and :MEMBER_OF edges is
# removed in v2. Belief synthesis is driven by SYNTHESIZED_FROM edges directly
# between :Belief and :Fact nodes. These queries are dead code.
# GET_CLUSTERS_FOR_NODES = ...            # removed
# GET_CLUSTERS_FOR_NODES_WITH_FACTS = ... # removed

# DEPRECATED (CITE v2): :Cluster nodes and all cluster membership / hierarchy
# queries are removed in v2. Belief synthesis uses SYNTHESIZED_FROM edges
# directly. Leiden community detection is no longer run on the graph.
# TODO: remove stubs after all callers are updated to v2 APIs
# Backwards-compat stubs below - return empty results; callers should migrate to v2.
DELETE_ALL_CLUSTERS = "RETURN 0 AS deleted_count"
BATCH_CREATE_PART_OF = "RETURN 0 AS created_count"
BATCH_UPDATE_CLUSTER_SUMMARIES = "RETURN 0 AS updated_count"
BATCH_CREATE_MEMBER_OF = "RETURN 0 AS created_count"

# Node importance update still valid for content nodes (used by PageRank scorer).
BATCH_UPDATE_NODE_IMPORTANCE = f"""
UNWIND $updates AS u
MATCH (n {{id: u.node_id, silo_id: $silo_id}})
WHERE {content_union_predicate("n")}
SET n.importance = u.rank
RETURN count(n) as updated
"""

# --- CITE v2 Claim write-path queries ---
# In v2, Claims are linked to Memory nodes via DERIVED_FROM (not EXTRACTED_FROM).
# Entity mentions use ABOUT edges (not MENTIONS -> :Entity).

ATTACH_CLAIM_TO_MEMORY = """
MATCH (m:Memory {id: $passage_id, silo_id: $silo_id})
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (c)-[:DERIVED_FROM]->(m)
"""

# Alias retained for callers that used the old name.
ATTACH_CLAIM_TO_PASSAGE = ATTACH_CLAIM_TO_MEMORY

# DEPRECATED (CITE v2): :Entity nodes and MENTIONS edges are removed.
# Use ABOUT edges to link Claims to target concepts expressed as node ids.
# UPSERT_ENTITY_MENTION = ...  # removed

PROMOTE_CLAIM_TO_FACT = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
OPTIONAL MATCH (c)<-[:PROMOTED_FROM]-(existing:Fact)
WITH c WHERE existing IS NULL
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

# Batch variant: accepts a list of rows, each with claim_id_a, claim_id_b, edge_id.
# Eliminates N+1 round trips when writing multiple CONTRADICTS edges in one call.
# Parameters: rows (list[{claim_id_a, claim_id_b, edge_id}]), silo_id.
BATCH_CREATE_CONTRADICTS_EDGES = """
UNWIND $rows AS r
MATCH (a:Claim {id: r.claim_id_a, silo_id: $silo_id})
MATCH (b:Claim {id: r.claim_id_b, silo_id: $silo_id})
MERGE (a)-[:CONTRADICTS {id: r.edge_id}]->(b)
RETURN count(*) AS edges_written
"""


def build_batch_entity_rel_query(rel_type: RelationshipType) -> str:
    """Build a batch CREATE entity relationship query with a real edge label.

    DEPRECATED (CITE v2): Entity-to-entity edges are removed in v2.
    Kept for backward compatibility until all callers are updated.
    """
    label = rel_type.value  # guaranteed member of the closed enum
    return f"""
UNWIND $rels AS r
MATCH (a:Entity {{id: r.source_id, silo_id: $silo_id}})
MATCH (b:Entity {{id: r.target_id, silo_id: $silo_id}})
CREATE (a)-[:{label} {{
    kind: r.kind,
    directed: r.directed,
    confidence: r.confidence,
    temporal: r.temporal,
    source_node_ids: r.source_node_ids,
    created_at: r.created_at
}}]->(b)
RETURN count(*) as created
"""


# DEPRECATED (CITE v2): :Entity nodes are removed. This query is kept for
# backward compatibility until extraction pipeline callers are updated.
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

# Per-seed heat batch read for PPR restart-vector weighting (phase-5.2).
# In v2 :Cluster nodes are removed; cluster_tier always returns null.
GET_SEED_HEAT_BATCH = """
UNWIND $seed_ids AS sid
MATCH (n {id: sid, silo_id: $silo_id})
WHERE n.committed = true
  AND n.tombstoned_at IS NULL
RETURN n.id AS node_id,
       coalesce(n.heat_score, 0.0) AS heat,
       null AS cluster_tier
"""

# ---------------------------------------------------------------------------
# Agent node queries (v1.5 phase 5a)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Chain handoff queries (v1.5 phase 5c)
# ---------------------------------------------------------------------------

# Validate that a :ReasoningChain exists in the same silo before writing a
# CONTINUES edge.  Returns the chain id if found.
GET_REASONING_CHAIN_IN_SILO = """
MATCH (c:ReasoningChain {id: $chain_id, silo_id: $silo_id})
RETURN c.id AS chain_id
"""

# Create a CONTINUES edge from a child chain to its parent chain.
# Direction: child_chain -[:CONTINUES]-> parent_chain.
# Single-inheritance enforced by the caller (one CONTINUES per child).
# Caller must verify parent exists in the same silo first
# (GET_REASONING_CHAIN_IN_SILO).
CREATE_CONTINUES_EDGE = """
MATCH (child:ReasoningChain {id: $child_chain_id, silo_id: $silo_id})
MATCH (parent:ReasoningChain {id: $parent_chain_id, silo_id: $silo_id})
MERGE (child)-[r:CONTINUES {created_at: $created_at}]->(parent)
RETURN child.id AS child_id, parent.id AS parent_id
"""

# Upsert an :Agent node. Returns the agent_id on both create and match.
# Role is updated on both create and match to allow role changes.
UPSERT_AGENT = """
MERGE (a:Agent {agent_id: $agent_id, silo_id: $silo_id})
ON CREATE SET
    a.role = $role,
    a.lineage_root_id = $lineage_root_id,
    a.created_at = $created_at
ON MATCH SET
    a.role = $role
RETURN a.agent_id AS agent_id
"""

# Validate that a parent :Agent exists in the same silo before creating a
# SPAWNED_BY edge. Returns the agent_id and lineage_root_id if found.
GET_AGENT_IN_SILO = """
MATCH (a:Agent {agent_id: $agent_id, silo_id: $silo_id})
RETURN a.agent_id AS agent_id, a.lineage_root_id AS lineage_root_id
"""

# Create a SPAWNED_BY edge from child agent to parent agent.
# Caller must verify parent exists in the same silo first (GET_AGENT_IN_SILO).
CREATE_SPAWNED_BY_EDGE = """
MATCH (child:Agent {agent_id: $child_agent_id, silo_id: $silo_id})
MATCH (parent:Agent {agent_id: $parent_agent_id, silo_id: $silo_id})
MERGE (child)-[r:SPAWNED_BY {created_at: $created_at}]->(parent)
RETURN child.agent_id AS child_id, parent.agent_id AS parent_id
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
    coalesce(ns[i].type, labels(ns[i])[0]) AS layer,
    CASE WHEN i < size(rs) THEN type(rs[i]) ELSE null END AS relationship,
    coalesce(ns[i].confidence, 1.0) AS confidence,
    coalesce(ns[i].stub, false) AS stub,
    length(path) AS depth
RETURN DISTINCT node_id, layer, relationship, confidence, stub
ORDER BY depth
"""

# Leaf sources: nodes in the provenance chain with no further outbound edges
PROVENANCE_ROOT_SOURCES = """
MATCH path = (start {id: $node_id, silo_id: $silo_id})-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM|REFERENCES*1..10]->(source)
OPTIONAL MATCH (source)-[:DERIVED_FROM|PROMOTED_FROM|SYNTHESIZED_FROM|REFERENCES]->(downstream)
WITH source, downstream
WHERE downstream IS NULL
RETURN DISTINCT
    source.id AS node_id,
    coalesce(source.type, labels(source)[0]) AS layer,
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

# Bidirectional supersession chain traversal.
# Walks both directions from any node in a chain to return the full history.
# Edge direction: (newer)-[:SUPERSEDES]->(older)
# Walking <- finds newer versions, walking -> finds older versions.
BELIEF_HISTORY_BIDIRECTIONAL = """
MATCH (start {id: $node_id, silo_id: $silo_id})
OPTIONAL MATCH (start)<-[:SUPERSEDES*1..20]-(newer)
WHERE newer.silo_id = $silo_id
WITH start, collect(DISTINCT newer) AS newer_nodes
OPTIONAL MATCH (start)-[:SUPERSEDES*1..20]->(older)
WHERE older.silo_id = $silo_id
WITH start, newer_nodes, collect(DISTINCT older) AS older_nodes
WITH [start] + newer_nodes + older_nodes AS all_raw
UNWIND all_raw AS n
WITH DISTINCT n
WHERE n IS NOT NULL
OPTIONAL MATCH (superseder)-[:SUPERSEDES]->(n)
WHERE superseder.silo_id = $silo_id
RETURN
    n.id AS node_id,
    n.content AS content,
    n.valid_from AS valid_from,
    n.valid_to AS valid_to,
    n.confidence AS confidence,
    n.supersession_reason AS supersession_reason,
    n.tombstoned_at AS tombstoned_at,
    superseder.id AS superseded_by
ORDER BY coalesce(n.valid_from, datetime('1970-01-01T00:00:00Z')) ASC
"""

# Meta-memory: reflections about a node filtered by agent_id.
# Pass $agent_id = null to return observations from all agents.
GET_REFLECTIONS_FOR_NODE_BY_AGENT = """
MATCH (obs:MetaObservation)-[:ABOUT]->(n {id: $node_id, silo_id: $silo_id})
WHERE obs.silo_id = $silo_id
  AND obs.tombstoned_at IS NULL
  AND ($agent_id IS NULL OR obs.agent_id = $agent_id)
RETURN
    obs.id AS node_id,
    obs.content AS content,
    obs.observation_type AS observation_type,
    obs.confidence AS confidence,
    obs.agent_id AS agent_id,
    obs.created_at AS created_at
ORDER BY obs.created_at DESC
"""

# Get reflection depths for MetaObservation targets (for hierarchical reflection)
GET_META_OBSERVATION_DEPTHS = """
MATCH (obs:MetaObservation {silo_id: $silo_id})
WHERE obs.id IN $target_ids AND obs.tombstoned_at IS NULL
RETURN obs.id AS id, coalesce(obs.reflection_depth, 1) AS reflection_depth
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
  AND n.tombstoned_at IS NULL
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
    n.source_tier = c.source_tier,
    n.created_at = c.created_at,
    n.committed = true
RETURN n.id AS id
"""

BATCH_ATTACH_CLAIMS_TO_MEMORY = """
UNWIND $rows AS r
MATCH (m:Memory {id: r.doc_id, silo_id: $silo_id})
MATCH (c:Claim {id: r.claim_id, silo_id: $silo_id})
MERGE (c)-[:DERIVED_FROM]->(m)
RETURN count(*) AS attached
"""

# Alias retained for callers that used the old name.
BATCH_ATTACH_CLAIMS_TO_DOCUMENT = BATCH_ATTACH_CLAIMS_TO_MEMORY

# DEPRECATED (CITE v2): :Entity nodes and MENTIONS edges removed.
# BATCH_UPSERT_ENTITY_MENTIONS = ...  # removed

BATCH_ATTACH_CLAIM_REFERENCES = """
UNWIND $rows AS r
MATCH (c:Claim {id: r.claim_id, silo_id: $silo_id})
MATCH (m:Memory {id: r.ref_doc_id, silo_id: $silo_id})
MERGE (c)-[:DERIVED_FROM]->(m)
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
    "  AND n.tombstoned_at IS NULL "
    "RETURN n.id AS id, n.content AS content, labels(n) AS labels, "
    "       n.confidence AS confidence, n.valid_from AS valid_from, "
    "       n.valid_to AS valid_to, n.created_at AS created_at "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)

# --- Temporal query with semantic pre-filter ---
# candidate_ids comes from a Qdrant pre-filter (top 3*top_k by vector similarity).
# Results are still ordered by valid_from DESC — Qdrant ranking is discarded here.

TEMPORAL_QUERY_FILTERED = (
    "MATCH (n) "
    "WHERE n.silo_id = $silo_id "
    "  AND n.id IN $candidate_ids "
    "  AND ($type_filter IS NULL OR any(label IN labels(n) WHERE label = $type_filter)) "
    "  AND n.valid_from <= $as_of "
    "  AND (n.valid_to IS NULL OR n.valid_to > $as_of) "
    "  AND n.content IS NOT NULL "
    "  AND n.tombstoned_at IS NULL "
    "RETURN n.id AS id, n.content AS content, labels(n) AS labels, "
    "       n.confidence AS confidence, n.valid_from AS valid_from, "
    "       n.valid_to AS valid_to, n.created_at AS created_at "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)

# --- Temporal fetch by explicit node IDs ---
# Returns all requested nodes with temporal metadata for classification.
# Classification (valid/not_yet_valid/expired/not_found) done in Python.

GET_NODES_BY_IDS_TEMPORAL = """
UNWIND $node_ids AS nid
OPTIONAL MATCH (n {id: nid, silo_id: $silo_id})
WHERE n.tombstoned_at IS NULL AND n.committed = true
OPTIONAL MATCH (n)-[:SUPERSEDES]->(successor)
RETURN
    nid AS requested_id,
    n.id AS node_id,
    n.content AS content,
    labels(n) AS labels,
    n.confidence AS confidence,
    n.valid_from AS valid_from,
    n.valid_to AS valid_to,
    n.created_at AS created_at,
    n.committed AS committed,
    n.layer AS layer,
    n.summary AS summary,
    n.tags AS tags,
    n.source_uri AS source_uri,
    n.content_hash AS content_hash,
    successor.id AS superseded_by
"""

# --- Supersession chain traversal (belief history) ---

# ---------------------------------------------------------------------------
# Session compaction: ReasoningChain -> Event (Memory layer trace)
# ---------------------------------------------------------------------------

CREATE_REASONING_TRACE_EVENT = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MERGE (e:Memory {id: $event_id, silo_id: $silo_id})
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
    chain.compact_event_id = $event_id,
    chain.compacted_by_model = $compacted_by_model
RETURN chain.id AS chain_id
"""

GET_REASONING_CHAIN_FOR_COMPACTION = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
RETURN
    chain.id AS id,
    chain.step_count AS step_count,
    chain.first_step AS first_step,
    chain.final_step AS final_step,
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

# ---------------------------------------------------------------------------
# Session state management (v1.3c)
# ---------------------------------------------------------------------------

SET_CHAIN_SESSION_STATE = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
SET chain.session_state = $session_state,
    chain.session_state_updated_at = $updated_at
RETURN chain.id AS chain_id, chain.session_state AS session_state
"""

GET_CHAIN_FOR_CLOSE = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
RETURN
    chain.id AS id,
    chain.steps AS steps,
    chain.compact_summary AS compact_summary,
    chain.produced_by_agent_id AS agent_id,
    chain.session_state AS session_state,
    coalesce(chain.compacted, false) AS compacted,
    coalesce(size(coalesce(chain.steps, [])), 0) AS step_count
"""

# NOTE: REFERENCES here is an IntelligenceLayer chain-to-chain edge,
# not the deprecated CITE content edge REFERENCES -> DERIVED_FROM.
# :ReasoningChain is also deprecated in v2 but kept for active chains.
CREATE_CHAIN_REFERENCES_EDGE = """
MATCH (from_chain:ReasoningChain {id: $from_chain_id, silo_id: $silo_id})
MATCH (to_chain:ReasoningChain {id: $to_chain_id, silo_id: $silo_id})
MERGE (from_chain)-[r:REFERENCES {silo_id: $silo_id}]->(to_chain)
ON CREATE SET
    r.created_at = $created_at,
    r.reason = $reason
RETURN from_chain.id AS from_id, to_chain.id AS to_id
"""

# --- Supersession chain traversal (belief history) ---

# ---------------------------------------------------------------------------
# Belief synthesis queries (Wisdom layer)
# ---------------------------------------------------------------------------

# DEPRECATED (CITE v2): GET_FACTS_IN_CLUSTER and BATCH_GET_FACTS_BY_CLUSTERS
# used MEMBER_OF to link Facts to Clusters. In v2 the synthesizer selects
# Facts directly by semantic similarity / confidence without clustering.
# Use GET_FACTS_FOR_SYNTHESIS below instead.
# TODO: remove stubs after all callers are updated to v2 APIs
# Backwards-compat stub - returns empty result, callers should migrate to v2 API.
GET_FACTS_IN_CLUSTER = """
RETURN null AS fact_id, null AS content, null AS confidence LIMIT 0
"""
BATCH_GET_FACTS_BY_CLUSTERS = """
RETURN null AS cluster_id, null AS fact_ids LIMIT 0
"""

# Fetch Facts in a silo for synthesis, ordered by confidence.
GET_FACTS_FOR_SYNTHESIS = """
MATCH (f:Fact {silo_id: $silo_id})
WHERE f.tombstoned_at IS NULL
  AND (f.synthesized_at IS NULL OR f.synthesized_at < $since)
RETURN f.id AS fact_id, f.content AS content,
       coalesce(f.confidence, 1.0) AS confidence,
       f.valid_from AS valid_from
ORDER BY coalesce(f.confidence, 1.0) DESC
LIMIT $limit
"""

# Batch version of GET_CHAINS_FOR_COMMITMENT for N+1 fix (P-02).
BATCH_GET_CHAINS_BY_COMMITMENTS = """
UNWIND $commitment_ids AS cid
MATCH (chain:ReasoningChain)-[:CRYSTALLIZED_INTO]->(c {id: cid, silo_id: $silo_id})
WHERE chain.status = 'published' AND chain.silo_id = $silo_id
RETURN c.id AS commitment_id, chain.id AS id,
       chain.produced_by_agent_id AS produced_by_agent_id,
       COALESCE(chain.confidence, 0.5) AS confidence
ORDER BY c.id, chain.id
"""

# Batch tag update for N+1 fix (P-03).
# NOTE: Uses Memgraph internal id(n) rather than n.id + silo_id. This is
# pre-existing behavior from the original per-node query. Tech debt: should
# refactor auto_tagging asset to use application-level IDs for silo isolation.
BATCH_UPDATE_NODE_TAGS = """
UNWIND $updates AS u
MATCH (n)
WHERE id(n) = u.node_id
SET n.tags = u.tags, n.auto_tagged_at = u.now
"""

# Batch mark Memory nodes as extracted (N+1 fix P-04).
BATCH_MARK_DOCS_EXTRACTED = """
UNWIND $doc_ids AS did
MATCH (d:Memory {id: did, silo_id: $silo_id})
SET d.extracted_at = $extracted_at
"""

# Create a :Belief node. Fact edges created separately via CREATE_BELIEF_FACT_EDGES.
CREATE_BELIEF_FROM_FACTS = """
MERGE (b:Belief {id: $belief_id, silo_id: $silo_id})
ON CREATE SET
    b.content = $content,
    b.confidence = $confidence,
    b.evidence_count = $evidence_count,
    b.created_at = $created_at,
    b.valid_from = $valid_from,
    b.valid_to = null
RETURN b.id AS belief_id
"""

CREATE_BELIEF_FACT_EDGES = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
UNWIND $fact_ids AS fid
MATCH (f:Fact {id: fid, silo_id: $silo_id})
MERGE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN count(f) AS edges_created
"""

# Check whether a :Belief already exists whose content covers the subject
# (case-insensitive substring match).  Used before synthesis to skip
# redundant work.
CHECK_BELIEF_COVERAGE = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE toLower(b.content) CONTAINS toLower($subject)
  AND (b.valid_to IS NULL OR b.valid_to > $as_of)
  AND b.tombstoned_at IS NULL
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

# Create :SUPERSEDES edge between Beliefs with pointer updates for O(1) lookups.
# Only sets tail_id if not already set (first supersession defines chain).
# Parameters: new_belief_id, old_belief_id, silo_id, reason (str), created_at (ISO datetime str).
CREATE_BELIEF_SUPERSEDES = """
MATCH (newer:Belief {id: $new_belief_id, silo_id: $silo_id})
MATCH (older:Belief {id: $old_belief_id, silo_id: $silo_id})
MERGE (newer)-[r:SUPERSEDES {
    reason: $reason,
    created_at: $created_at
}]->(older)
WITH newer, older, COALESCE(older.tail_id, older.id) AS derived_tail_id
// Only set tail_id if not already set (first supersession defines chain)
FOREACH (_ IN CASE WHEN newer.tail_id IS NULL THEN [1] ELSE [] END |
  SET newer.tail_id = derived_tail_id
)
WITH newer, COALESCE(newer.tail_id, derived_tail_id) AS tail_id
MATCH (tail:Belief {id: tail_id, silo_id: $silo_id})
SET tail.head_id = newer.id
RETURN tail.id AS tail_id
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
# DEPRECATED (CITE v2): Pattern queries
#
# :Pattern nodes and OBSERVED_IN edges are removed in v2. Temporal correlation
# and co-occurrence detection relied on :Cluster / MEMBER_OF which are also
# gone. Causal chain detection (CAUSES edges) was speculative and unused.
#
# TODO: remove stubs after all callers are updated to v2 APIs
# Backwards-compat stubs for pattern queries - return empty results.
CREATE_PATTERN = "RETURN null AS pattern_id LIMIT 0"
UPDATE_PATTERN_FREQUENCY = "RETURN 0 AS updated"
GET_PATTERN_BY_TYPE_AND_SUBJECT = "RETURN null AS pattern_id LIMIT 0"
DETECT_TEMPORAL_CORRELATIONS = "RETURN null AS pattern_id LIMIT 0"
DETECT_CO_OCCURRING_FACTS = "RETURN null AS pattern_id LIMIT 0"
DETECT_CAUSAL_CHAINS = "RETURN null AS pattern_id LIMIT 0"
DECAY_STALE_PATTERNS = "RETURN 0 AS decayed"
TOMBSTONE_LOW_CONFIDENCE_PATTERNS = "RETURN 0 AS tombstoned"
#
# Temporal correlation is replaced by bitemporal edges in the SAGE synthesizer.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Belief merging queries (v1.4 Phase 4a)
# ---------------------------------------------------------------------------

# Find :Belief nodes in a silo whose content shares the same subject (case-
# insensitive substring match) and whose centroid embedding cosine similarity
# exceeds a threshold.  Returns up to $limit candidates along with their
# fact ids so the merge function can union them.
# Parameters: silo_id, subject (str), limit (int).
FIND_SIMILAR_BELIEFS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE toLower(b.content) CONTAINS toLower($subject)
  AND (b.valid_to IS NULL OR b.valid_to > $as_of)
  AND b.tombstoned_at IS NULL
OPTIONAL MATCH (b)-[:SYNTHESIZED_FROM]->(f:Fact {silo_id: $silo_id})
WITH b, collect(f.id) AS fact_ids
RETURN b.id AS belief_id, b.content AS content,
       coalesce(b.confidence, 1.0) AS confidence,
       fact_ids
ORDER BY confidence DESC
LIMIT $limit
"""

# Create a merged :Belief node and attach SYNTHESIZED_FROM edges to all
# unioned fact ids in one write.
# Parameters: belief_id, silo_id, content, confidence, evidence_count,
#             created_at, valid_from, fact_ids (list[str]).
CREATE_MERGED_BELIEF = """
MERGE (b:Belief {id: $belief_id, silo_id: $silo_id})
ON CREATE SET
    b.content = $content,
    b.confidence = $confidence,
    b.evidence_count = $evidence_count,
    b.created_at = $created_at,
    b.valid_from = $valid_from,
    b.valid_to = null,
    b.merged = true
RETURN b.id AS belief_id
"""

CREATE_MERGED_BELIEF_FACT_EDGES = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
UNWIND $fact_ids AS fid
MATCH (f:Fact {id: fid, silo_id: $silo_id})
MERGE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN count(f) AS edges_created
"""

# Attach MERGED_FROM edges from the new merged :Belief to each source belief.
# Parameters: merged_belief_id, silo_id, source_belief_ids (list[str]),
#             created_at (ISO datetime str).
CREATE_MERGED_FROM_EDGES = """
MATCH (merged:Belief {id: $merged_belief_id, silo_id: $silo_id})
UNWIND $source_belief_ids AS sid
MATCH (source:Belief {id: sid, silo_id: $silo_id})
MERGE (merged)-[r:MERGED_FROM {created_at: $created_at}]->(source)
RETURN count(r) AS edges_created
"""

# ---------------------------------------------------------------------------
# Multi-chain session queries (v1.4 Phase 4c)
# ---------------------------------------------------------------------------

# Create or return an existing open :ReasoningSession node.
CREATE_REASONING_SESSION = """
MERGE (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
ON CREATE SET
    s.status = 'open',
    s.created_at = $created_at,
    s.updated_at = $created_at
ON MATCH SET
    s.updated_at = $created_at
RETURN s.id AS session_id, s.status AS status
"""

# Attach a :ReasoningChain to an existing :ReasoningSession via PART_OF_SESSION.
ATTACH_CHAIN_TO_SESSION = """
MATCH (c:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MATCH (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
MERGE (c)-[r:PART_OF_SESSION]->(s)
ON CREATE SET r.created_at = $created_at
RETURN c.id AS chain_id, s.id AS session_id
"""

# Fetch the status of a single :ReasoningSession by id.
GET_SESSION_STATUS = """
MATCH (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
RETURN s.id AS session_id, s.status AS status
"""

# Return open :ReasoningSession nodes whose updated_at is older than $stale_before.
GET_STALE_OPEN_SESSIONS = """
MATCH (s:ReasoningSession {silo_id: $silo_id, status: 'open'})
WHERE s.updated_at < $stale_before
RETURN s.id AS session_id, s.updated_at AS updated_at
"""

# Return all :ReasoningChain nodes attached to a session (not yet compacted).
GET_SESSION_CHAINS = """
MATCH (c:ReasoningChain)-[:PART_OF_SESSION]->(s:ReasoningSession {id: $session_id, silo_id: $silo_id})
RETURN c.id AS chain_id, coalesce(c.status, 'open') AS status,
       coalesce(c.compacted, false) AS compacted
"""

# Mark a :ReasoningSession as closed.
CLOSE_REASONING_SESSION = """
MATCH (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
SET s.status = 'closed',
    s.closed_at = $closed_at
RETURN s.id AS session_id
"""

# Cross-chain REFERENCES edges within the same session.
# NOTE: REFERENCES here is an IntelligenceLayer chain-to-chain edge,
# not the deprecated CITE content edge REFERENCES -> DERIVED_FROM.
CREATE_CROSS_CHAIN_REFERENCES = """
MATCH (a:ReasoningChain)-[:PART_OF_SESSION]->(s:ReasoningSession {id: $session_id, silo_id: $silo_id})
MATCH (b:ReasoningChain)-[:PART_OF_SESSION]->(s)
WHERE a.id <> b.id AND a.created_at < b.created_at
MERGE (a)-[r:REFERENCES {silo_id: $silo_id, reason: 'same_session', created_at: $created_at}]->(b)
RETURN count(r) AS edges_created
"""

# List all open sessions across all silos (used by auto-close sensor).
GET_ALL_STALE_OPEN_SESSIONS = """
MATCH (s:ReasoningSession {status: 'open'})
WHERE s.updated_at < $stale_before
RETURN s.id AS session_id, s.silo_id AS silo_id, s.updated_at AS updated_at
"""

# ---------------------------------------------------------------------------
# Partial revision + cascade flagging queries (v1.4 Phase 4b)
# ---------------------------------------------------------------------------

# Find all :Belief nodes that reference a given belief via SYNTHESIZED_FROM,
# REVISED_FROM, MERGED_FROM, or REFERENCES edges.  Used to identify downstream
# beliefs that must be flagged for review when the referenced belief changes.
# Parameters: belief_id (str), silo_id (str).
FIND_BELIEFS_REFERENCING = """
MATCH (target:Belief {id: $belief_id, silo_id: $silo_id})
MATCH (b:Belief {silo_id: $silo_id})-[:SYNTHESIZED_FROM|REVISED_FROM|MERGED_FROM|REFERENCES]->(target)
WHERE b.tombstoned_at IS NULL
RETURN b.id AS belief_id, b.content AS content,
       coalesce(b.confidence, 1.0) AS confidence,
       coalesce(b.wisdom_status, 'active') AS wisdom_status
"""

# Set revision_cascade_pending = true on a set of :Belief nodes to mark them
# for review by the custodian.
# Parameters: belief_ids (list[str]), silo_id (str), flagged_at (ISO str).
FLAG_CASCADE_PENDING = """
UNWIND $belief_ids AS bid
MATCH (b:Belief {id: bid, silo_id: $silo_id})
SET b.revision_cascade_pending = true,
    b.cascade_flagged_at = $flagged_at
RETURN count(b) AS flagged
"""

# Return all :Belief nodes in a silo that have revision_cascade_pending = true.
# Parameters: silo_id (str), limit (int).
GET_CASCADE_PENDING_BELIEFS = """
MATCH (b:Belief {silo_id: $silo_id})
WHERE b.revision_cascade_pending = true
  AND b.tombstoned_at IS NULL
RETURN b.id AS belief_id, b.content AS content,
       coalesce(b.confidence, 1.0) AS confidence,
       b.cascade_flagged_at AS cascade_flagged_at,
       coalesce(b.wisdom_status, 'active') AS wisdom_status
ORDER BY b.cascade_flagged_at ASC
LIMIT $limit
"""

# Clear revision_cascade_pending flag after the custodian processes a belief.
# Parameters: belief_id (str), silo_id (str).
CLEAR_CASCADE_PENDING = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
REMOVE b.revision_cascade_pending
SET b.cascade_processed_at = $processed_at
RETURN b.id AS belief_id
"""

GET_SUPERSESSION_CHAIN = (
    "MATCH (start {id: $start_id, silo_id: $silo_id}) "
    "OPTIONAL MATCH path = (start)-[:SUPERSEDES*0..20]->(related) "
    "WHERE ALL(x IN nodes(path) WHERE x.silo_id = $silo_id) "
    "WITH collect(DISTINCT related) + [start] AS all_nodes "
    "UNWIND all_nodes AS n "
    "WITH DISTINCT n "
    "OPTIONAL MATCH (superseded_by_node)-[:SUPERSEDES]->(n) "
    "RETURN n.id AS id, n.content AS content, "
    "       n.confidence AS confidence, "
    "       n.valid_from AS valid_from, n.valid_to AS valid_to, "
    "       superseded_by_node.id AS superseded_by "
    "ORDER BY n.valid_from DESC "
    "LIMIT $limit"
)

# --- Conclusion queries ---

UPSERT_CONCLUSION = """
MERGE (c:Conclusion {id: $id, silo_id: $silo_id})
ON CREATE SET
    c.silo_id = $silo_id,
    c.query_context_hash = $query_context_hash,
    c.content = $content,
    c.confidence = $confidence,
    c.status = $status,
    c.created_by_agent_id = $created_by_agent_id,
    c.created_at = $created_at,
    c.valid_from = $valid_from,
    c.valid_to = null
ON MATCH SET
    c.content = $content,
    c.confidence = $confidence,
    c.status = $status
RETURN c
"""

CREATE_CONSOLIDATES_EDGE = """
MATCH (canonical:Conclusion {id: $canonical_id, silo_id: $silo_id})
MATCH (original:Conclusion {id: $original_id, silo_id: $silo_id})
MERGE (canonical)-[:CONSOLIDATES]->(original)
"""

GET_CONCLUSIONS_BY_HASH = """
MATCH (c:Conclusion {silo_id: $silo_id, query_context_hash: $query_context_hash})
WHERE c.status = 'active'
RETURN c
"""

MARK_CONCLUSION_CONSOLIDATED = """
MATCH (c:Conclusion {id: $id, silo_id: $silo_id})
SET c.status = 'consolidated'
RETURN c
"""

# --- Crystallization edges (Intelligence -> Knowledge) ---

# Link a ReasoningChain to a Commitment (Wisdom layer).
# Used by decide() when a reasoning parameter is provided to attach
# the auto-created chain to the resulting Commitment node.
LINK_CHAIN_TO_COMMITMENT = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MATCH (c:Commitment {id: $commitment_id, silo_id: $silo_id})
MERGE (chain)-[:CRYSTALLIZED_INTO]->(c)
"""

CREATE_CRYSTALLIZES_EDGE = """
MATCH (chain:ReasoningChain {id: $chain_id, silo_id: $silo_id})
MATCH (claim:Claim {id: $claim_id, silo_id: $silo_id})
MERGE (chain)-[:CRYSTALLIZES {created_at: $created_at}]->(claim)
"""

BATCH_CREATE_CRYSTALLIZES_EDGES = """
UNWIND $edges AS e
MATCH (chain:ReasoningChain {id: e.chain_id, silo_id: e.silo_id})
MATCH (claim:Claim {id: e.claim_id, silo_id: e.silo_id})
MERGE (chain)-[:CRYSTALLIZES {created_at: e.created_at}]->(claim)
"""

BATCH_CREATE_DERIVED_FROM_EDGES = """
UNWIND $ev_ids AS ev_id
MATCH (claim {id: $claim_id, silo_id: $silo_id}), (ev {id: ev_id, silo_id: $silo_id})
MERGE (claim)-[:DERIVED_FROM]->(ev)
"""

BATCH_CREATE_ABOUT_EDGES = """
UNWIND $target_ids AS target_id
MATCH (src {id: $src_id, silo_id: $silo_id}), (target {id: target_id, silo_id: $silo_id})
MERGE (src)-[:ABOUT]->(target)
"""


# ---------------------------------------------------------------------------
# Working hypothesis queries (Intelligence layer, session-scoped)
#
# WorkingHypothesis nodes are mutable, ephemeral, attached to a ReasoningSession.
# They represent what an agent currently thinks during a session and can be
# crystallized into durable Commitments at session end (or earlier).
# ---------------------------------------------------------------------------

# Create a :WorkingHypothesis node, attach it to its :ReasoningSession via
# PART_OF_SESSION, and create :ABOUT edges to each node id in $about_ids.
# Caller must ensure the :ReasoningSession exists in the same silo.
CREATE_WORKING_HYPOTHESIS = """
CREATE (wb:WorkingHypothesis {
    id: $id,
    silo_id: $silo_id,
    session_id: $session_id,
    content: $content,
    confidence: $confidence,
    created_at: $created_at,
    updated_at: $created_at
})
WITH wb
MATCH (s:ReasoningSession {id: $session_id, silo_id: $silo_id})
CREATE (wb)-[:PART_OF_SESSION]->(s)
WITH wb
UNWIND $about_ids AS about_id
MATCH (n {id: about_id, silo_id: $silo_id})
CREATE (wb)-[:ABOUT]->(n)
RETURN wb.id AS belief_id
"""

# Return all :WorkingHypothesis nodes attached to a session, with the ids of
# the nodes they reference via :ABOUT collected per belief.
GET_WORKING_HYPOTHESES_FOR_SESSION = """
MATCH (wb:WorkingHypothesis {session_id: $session_id, silo_id: $silo_id})
OPTIONAL MATCH (wb)-[:ABOUT]->(n)
WITH wb, collect(n.id) AS about_ids
RETURN wb.id AS belief_id,
       wb.content AS content,
       wb.confidence AS confidence,
       wb.created_at AS created_at,
       wb.updated_at AS updated_at,
       wb.agent_id AS agent_id,
       wb.traced_at AS traced_at,
       wb.crystallized_into AS crystallized_into,
       about_ids
ORDER BY wb.created_at DESC
"""

# In-place update of a :WorkingHypothesis. $content may be null to leave content
# unchanged; confidence and updated_at are always set.
UPDATE_WORKING_HYPOTHESIS = """
MATCH (wb:WorkingHypothesis {id: $belief_id, silo_id: $silo_id})
SET wb.confidence = $confidence,
    wb.updated_at = $updated_at
SET wb.content = CASE WHEN $content IS NOT NULL THEN $content ELSE wb.content END
RETURN wb.id AS belief_id, wb.confidence AS confidence
"""

DELETE_WORKING_HYPOTHESIS = """
MATCH (wb:WorkingHypothesis {id: $belief_id, silo_id: $silo_id})
DETACH DELETE wb
"""

# Sync conflict detection: given a freshly-written :WorkingHypothesis, return the
# ids of any other :WorkingHypothesis in the same session that ABOUT the same
# node(s). Bounded by LIMIT 10 to keep p99 under ~30ms.
DETECT_CONFLICTING_WORKING_HYPOTHESES = """
MATCH (new:WorkingHypothesis {id: $new_belief_id, silo_id: $silo_id})
MATCH (new)-[:ABOUT]->(n)
MATCH (other:WorkingHypothesis)-[:ABOUT]->(n)
WHERE other.id <> $new_belief_id
  AND other.session_id = new.session_id
RETURN DISTINCT other.id AS conflict_id
LIMIT 10
"""

# Pairwise contradiction detection across a whole session. Returns up to 10
# unordered pairs of WorkingHypotheses that share at least one ABOUT target.
DETECT_CONTRADICTIONS_IN_SESSION = """
MATCH (wb1:WorkingHypothesis {session_id: $session_id, silo_id: $silo_id})
MATCH (wb2:WorkingHypothesis {session_id: $session_id, silo_id: $silo_id})
WHERE wb1.id < wb2.id
MATCH (wb1)-[:ABOUT]->(n)<-[:ABOUT]-(wb2)
RETURN DISTINCT wb1.id AS belief_a, wb2.id AS belief_b
LIMIT 10
"""

# Promote a :WorkingHypothesis to a durable :Commitment, copy its ABOUT edges,
# and SUPERSEDE any existing active Commitments that ABOUT the same node(s).
# Existing commitments are considered active when no other Commitment
# SUPERSEDES them. Their valid_to is set to $valid_from on supersession.
# Sets tail_id/head_id pointers for O(1) chain lookups.
# Only sets tail_id on first supersession (first chain wins for multi-supersession).
CRYSTALLIZE_TO_COMMITMENT = """
MATCH (wb:WorkingHypothesis {id: $belief_id, silo_id: $silo_id})
CREATE (cm:Commitment {
    id: $commitment_id,
    silo_id: $silo_id,
    layer: "wisdom",
    content: wb.content,
    confidence: wb.confidence,
    created_at: $created_at,
    valid_from: $valid_from,
    crystallized_from: wb.id,
    rationale_chain_id: $rationale_chain_id
})
WITH wb, cm
MATCH (wb)-[:ABOUT]->(n)
CREATE (cm)-[:ABOUT]->(n)
WITH DISTINCT wb, cm
OPTIONAL MATCH (cm)-[:ABOUT]->(shared_node)<-[:ABOUT]-(existing:Commitment {silo_id: $silo_id})
WHERE existing.id <> cm.id
WITH wb, cm, collect(DISTINCT existing) AS candidates
DETACH DELETE wb
WITH cm, candidates
UNWIND (CASE WHEN size(candidates) = 0 THEN [null] ELSE candidates END) AS existing
WITH cm, existing WHERE existing IS NOT NULL
// Only supersede if existing is not already superseded
OPTIONAL MATCH (superseding:Commitment)-[:SUPERSEDES]->(existing)
WITH cm, existing, superseding WHERE superseding IS NULL
// Create supersession with pointers (first chain wins)
WITH cm, existing, COALESCE(existing.tail_id, existing.id) AS derived_tail_id
FOREACH (_ IN CASE WHEN cm.tail_id IS NULL THEN [1] ELSE [] END |
  SET cm.tail_id = derived_tail_id
)
CREATE (cm)-[:SUPERSEDES {reason: $reason, created_at: $created_at}]->(existing)
SET existing.valid_to = $valid_from
WITH cm, COALESCE(cm.tail_id, derived_tail_id) AS tail_id
MATCH (tail:Commitment {id: tail_id, silo_id: $silo_id})
SET tail.head_id = cm.id
RETURN cm.id AS commitment_id, cm.confidence AS confidence
"""


# ---------------------------------------------------------------------------
# DEPRECATED (CITE v2): ProposedBelief queries
#
# In v2 the separate :ProposedBelief node type is removed. SAGE synthesizes
# directly to :Belief nodes with status='pending'. Agents use accept() /
# dismiss() on :Belief nodes (not on a separate ProposedBelief).
#
# Replacement pattern:
#   CREATE_PROPOSED_BELIEF   -> CREATE_BELIEF_FROM_FACTS (sets status='pending')
#   GET_PROPOSED_BELIEFS_*   -> GET_PENDING_BELIEFS_FOR_SILO below
#   ACCEPT_PROPOSED_BELIEF   -> ACCEPT_PENDING_BELIEF below
#   REJECT_PROPOSED_BELIEF   -> REJECT_PENDING_BELIEF below
# ---------------------------------------------------------------------------

# Create a pending :Belief (SAGE synthesis output awaiting agent acceptance).
CREATE_PENDING_BELIEF = """
MERGE (b:Belief {id: $id, silo_id: $silo_id})
ON CREATE SET
    b.content = $content,
    b.confidence = $confidence,
    b.status = 'pending',
    b.layer = 'wisdom',
    b.created_at = $created_at,
    b.updated_at = $created_at,
    b.valid_from = $created_at,
    b.expires_at = $expires_at
WITH b
UNWIND $synthesized_from_ids AS fact_id
MATCH (f:Fact {id: fact_id, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN b.id AS proposed_belief_id
"""

GET_PENDING_BELIEFS_FOR_SILO = """
MATCH (b:Belief {silo_id: $silo_id, status: 'pending'})
WHERE b.tombstoned_at IS NULL
OPTIONAL MATCH (b)-[:SYNTHESIZED_FROM]->(f:Fact)
WITH b, collect(f.id) AS source_fact_ids
RETURN b.id AS proposed_belief_id,
       b.content AS content,
       b.confidence AS confidence,
       b.created_at AS created_at,
       source_fact_ids
ORDER BY b.created_at DESC
LIMIT $limit
"""

GET_PENDING_BELIEF = """
MATCH (b:Belief {id: $proposed_belief_id, silo_id: $silo_id})
OPTIONAL MATCH (b)-[:SYNTHESIZED_FROM]->(f:Fact)
WITH b, collect(f.id) AS source_fact_ids
RETURN b.id AS proposed_belief_id,
       b.content AS content,
       b.confidence AS confidence,
       b.status AS status,
       b.created_at AS created_at,
       b.accepted_at AS accepted_at,
       b.rejected_at AS rejected_at,
       b.rejection_reason AS rejection_reason,
       source_fact_ids
"""

ACCEPT_PENDING_BELIEF = """
MATCH (b:Belief {id: $proposed_belief_id, silo_id: $silo_id})
WHERE b.status = 'pending'
SET b.status = 'active',
    b.accepted_at = $accepted_at,
    b.updated_at = $accepted_at,
    b.confidence = CASE WHEN $override_confidence IS NOT NULL THEN $override_confidence ELSE b.confidence END
RETURN b.id AS belief_id, b.confidence AS confidence
"""

REJECT_PENDING_BELIEF = """
MATCH (b:Belief {id: $proposed_belief_id, silo_id: $silo_id})
WHERE b.status = 'pending'
SET b.status = 'rejected',
    b.rejected_at = $rejected_at,
    b.rejection_reason = $reason,
    b.updated_at = $rejected_at,
    b.tombstoned_at = $rejected_at
RETURN b.id AS proposed_belief_id, b.status AS status
"""

GET_PENDING_BELIEF_COUNT_FOR_SILO = """
MATCH (b:Belief {silo_id: $silo_id, status: 'pending'})
WHERE b.tombstoned_at IS NULL
RETURN count(b) AS pending_count
"""

DELETE_EXPIRED_PROPOSALS = """
MATCH (b:Belief {silo_id: $silo_id, status: 'pending'})
WHERE b.expires_at IS NOT NULL AND b.expires_at < $now
WITH b
WITH count(b) AS deleted_count, collect(b) AS to_delete
FOREACH (p IN to_delete | DETACH DELETE p)
RETURN deleted_count
"""

GET_PENDING_BELIEFS_FOR_FACTS = """
MATCH (b:Belief {silo_id: $silo_id, status: 'pending'})-[r:SYNTHESIZED_FROM]->(f:Fact {silo_id: $silo_id})
WHERE (b.expires_at IS NULL OR b.expires_at > datetime())
  AND b.tombstoned_at IS NULL
  AND f.id IN $about_ids
RETURN DISTINCT b.id AS id,
       b.content AS content,
       b.confidence AS confidence,
       b.status AS status,
       b.created_at AS created_at
ORDER BY b.created_at DESC
"""

# Backward-compat aliases for callers still using old names.
GET_PENDING_PROPOSAL_COUNT_FOR_SILO = GET_PENDING_BELIEF_COUNT_FOR_SILO
GET_PENDING_PROPOSED_BELIEFS_FOR_CLAIMS = GET_PENDING_BELIEFS_FOR_FACTS
GET_PROPOSED_BELIEFS_FOR_SILO = GET_PENDING_BELIEFS_FOR_SILO


# ---------------------------------------------------------------------------
# Marker queries (SAGE-internal validator types)
#
# Contradiction and StaleCommitment are bare-label marker nodes written by the
# SAGE validator/groundskeeper when it detects epistemic issues. Status
# transitions: pending -> resolved | dismissed.
# Agents engage via the about_ids index — a marker surfaces to the agent when
# one of its about_ids matches a node the agent recently touched.
# ---------------------------------------------------------------------------

CREATE_CONTRADICTION = """
CREATE (c:Contradiction {
    id: $id,
    silo_id: $silo_id,
    status: 'pending',
    node_a_id: $node_a_id,
    node_b_id: $node_b_id,
    about_ids: $about_ids,
    confidence: $confidence,
    detected_at: $detected_at,
    resolved_at: null,
    resolution: null,
    expires_at: $expires_at
})
RETURN c.id AS marker_id
"""

CREATE_STALE_COMMITMENT = """
CREATE (sc:StaleCommitment {
    id: $id,
    silo_id: $silo_id,
    status: 'pending',
    commitment_id: $commitment_id,
    evidence_ids: $evidence_ids,
    about_ids: $about_ids,
    detected_at: $detected_at,
    resolved_at: null,
    resolution: null,
    expires_at: $expires_at
})
RETURN sc.id AS marker_id
"""

GET_MARKERS_BY_SILO = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE $status IS NULL OR c.status = $status
    RETURN c.id AS id,
           'Contradiction' AS marker_type,
           c.status AS status,
           c.detected_at AS detected_at,
           c.expires_at AS expires_at,
           c.about_ids AS about_ids
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE $status IS NULL OR sc.status = $status
    RETURN sc.id AS id,
           'StaleCommitment' AS marker_type,
           sc.status AS status,
           sc.detected_at AS detected_at,
           sc.expires_at AS expires_at,
           sc.about_ids AS about_ids
}
RETURN id, marker_type, status, detected_at, expires_at, about_ids
ORDER BY detected_at DESC
LIMIT $limit
"""

GET_MARKERS_BY_ABOUT_ID = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE $about_id IN c.about_ids
    AND ($status IS NULL OR c.status = $status)
    RETURN c.id AS id,
           'Contradiction' AS marker_type,
           c.status AS status,
           c.detected_at AS detected_at,
           c.about_ids AS about_ids
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE $about_id IN sc.about_ids
    AND ($status IS NULL OR sc.status = $status)
    RETURN sc.id AS id,
           'StaleCommitment' AS marker_type,
           sc.status AS status,
           sc.detected_at AS detected_at,
           sc.about_ids AS about_ids
}
RETURN id, marker_type, status, detected_at, about_ids
ORDER BY detected_at DESC
"""

UPDATE_MARKER_STATUS = """
CALL {
    MATCH (c:Contradiction {id: $id, silo_id: $silo_id})
    SET c.status = $status,
        c.resolved_at = $resolved_at,
        c.resolution = $resolution
    RETURN c.id AS marker_id, 'Contradiction' AS marker_type
    UNION ALL
    MATCH (sc:StaleCommitment {id: $id, silo_id: $silo_id})
    SET sc.status = $status,
        sc.resolved_at = $resolved_at,
        sc.resolution = $resolution
    RETURN sc.id AS marker_id, 'StaleCommitment' AS marker_type
}
RETURN marker_id, marker_type
"""

GET_MARKERS_BY_IDS = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE c.id IN $ids
    RETURN c.id AS id,
           'Contradiction' AS marker_type,
           c.status AS status,
           c.detected_at AS detected_at,
           c.expires_at AS expires_at,
           c.about_ids AS about_ids,
           c.node_a_id AS node_a_id,
           c.node_b_id AS node_b_id,
           c.confidence AS confidence,
           null AS commitment_id,
           null AS evidence_ids,
           c.resolution AS resolution,
           c.resolved_at AS resolved_at
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE sc.id IN $ids
    RETURN sc.id AS id,
           'StaleCommitment' AS marker_type,
           sc.status AS status,
           sc.detected_at AS detected_at,
           sc.expires_at AS expires_at,
           sc.about_ids AS about_ids,
           null AS node_a_id,
           null AS node_b_id,
           null AS confidence,
           sc.commitment_id AS commitment_id,
           sc.evidence_ids AS evidence_ids,
           sc.resolution AS resolution,
           sc.resolved_at AS resolved_at
}
RETURN id, marker_type, status, detected_at, expires_at, about_ids,
       node_a_id, node_b_id, confidence, commitment_id, evidence_ids,
       resolution, resolved_at
"""

GET_EXPIRED_MARKERS = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE c.expires_at IS NOT NULL AND c.expires_at < $now
    RETURN c.id AS id, 'Contradiction' AS marker_type, c.about_ids AS about_ids
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE sc.expires_at IS NOT NULL AND sc.expires_at < $now
    RETURN sc.id AS id, 'StaleCommitment' AS marker_type, sc.about_ids AS about_ids
}
RETURN id, marker_type, about_ids
"""

DELETE_EXPIRED_MARKERS = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE c.expires_at IS NOT NULL AND c.expires_at < $now
    WITH c
    WITH count(c) AS cnt, collect(c) AS to_delete
    FOREACH (n IN to_delete | DETACH DELETE n)
    RETURN cnt AS deleted_contradictions
}
CALL {
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE sc.expires_at IS NOT NULL AND sc.expires_at < $now
    WITH sc
    WITH count(sc) AS cnt, collect(sc) AS to_delete
    FOREACH (n IN to_delete | DETACH DELETE n)
    RETURN cnt AS deleted_stale_commitments
}
RETURN deleted_contradictions, deleted_stale_commitments
"""

# Atomic delete+return for marker cleanup (race-condition safe)
# Combines GET_EXPIRED_MARKERS and DELETE_EXPIRED_MARKERS into single atomic query.
# Returns about_ids for Redis cleanup before deleting the nodes.
# Uses single CALL with UNION ALL inside for Memgraph compatibility.
DELETE_EXPIRED_MARKERS_ATOMIC = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id})
    WHERE c.expires_at IS NOT NULL AND c.expires_at < $now
    WITH c, c.id AS id, c.about_ids AS about_ids
    DETACH DELETE c
    RETURN id, 'Contradiction' AS marker_type, about_ids
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id})
    WHERE sc.expires_at IS NOT NULL AND sc.expires_at < $now
    WITH sc, sc.id AS id, sc.about_ids AS about_ids
    DETACH DELETE sc
    RETURN id, 'StaleCommitment' AS marker_type, about_ids
}
RETURN id, marker_type, about_ids
"""

# ---------------------------------------------------------------------------
# Contradiction candidate flag queries (validator Task 4)
#
# Nodes are flagged by Task 3 (inline detection) with three properties:
#   contradiction_candidate = true
#   contradiction_candidate_with = [node_id, ...] (one or more peer node ids)
#   contradiction_candidate_at = ISO datetime string
#
# The validator asset queries within a TTL window (1 h by default) so stale
# flags that were never confirmed do not accumulate indefinitely.
# ---------------------------------------------------------------------------

GET_CONTRADICTION_CANDIDATES = """
MATCH (n {silo_id: $silo_id})
WHERE n.contradiction_candidate = true
  AND n.contradiction_candidate_at > $cutoff
  AND n.contradiction_candidate_with IS NOT NULL
RETURN n.id AS node_id,
       n.content AS content,
       n.contradiction_candidate_with AS candidate_with_ids
LIMIT $limit
"""

CLEAR_CONTRADICTION_CANDIDATE_FLAGS = """
MATCH (n {id: $node_id, silo_id: $silo_id})
REMOVE n.contradiction_candidate,
       n.contradiction_candidate_with,
       n.contradiction_candidate_at
RETURN n.id AS node_id
"""

GET_NODES_CONTENT_BY_IDS = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
WHERE n.content IS NOT NULL
RETURN n.id AS node_id, n.content AS content
"""

GET_ALL_PENDING_MARKERS_FOR_SILO = """
CALL {
    MATCH (c:Contradiction {silo_id: $silo_id, status: 'pending'})
    WHERE c.expires_at IS NULL OR c.expires_at > datetime()
    RETURN c.id AS id,
           'Contradiction' AS marker_type,
           c.status AS status,
           c.detected_at AS detected_at,
           c.about_ids AS about_ids,
           c.node_a_id AS node_a_id,
           c.node_b_id AS node_b_id,
           null AS commitment_id
    UNION ALL
    MATCH (sc:StaleCommitment {silo_id: $silo_id, status: 'pending'})
    WHERE sc.expires_at IS NULL OR sc.expires_at > datetime()
    RETURN sc.id AS id,
           'StaleCommitment' AS marker_type,
           sc.status AS status,
           sc.detected_at AS detected_at,
           sc.about_ids AS about_ids,
           null AS node_a_id,
           null AS node_b_id,
           sc.commitment_id AS commitment_id
}
RETURN id, marker_type, status, detected_at, about_ids,
       node_a_id, node_b_id, commitment_id
ORDER BY detected_at DESC
"""

# TX8 COMMIT and TX14 CRYSTALLIZE queries

VALIDATE_ABOUT_REFS = """
UNWIND $node_ids AS nid
MATCH (n {id: nid, silo_id: $silo_id})
RETURN n.id AS id, n.properties.state AS state
"""

CREATE_COMMITMENT_WITH_ABOUT = """
CREATE (c:Commitment {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    properties: $props
})
WITH c
UNWIND $about_ids AS aid
MATCH (a {id: aid, silo_id: $silo_id})
CREATE (c)-[:ABOUT]->(a)
WITH c
MERGE (agent:Agent {id: $agent_id})
CREATE (c)-[:DECLARED_BY {created_at: $created_at}]->(agent)
RETURN c.id AS id
"""

GET_HYPOTHESIS_FOR_CRYSTALLIZE = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id, silo_id: $silo_id})
WHERE h.session_id = $session_id
RETURN h.id AS id,
       h.content AS content,
       h.confidence AS confidence,
       h.crystallized AS crystallized,
       h.state AS state
"""

GET_HYPOTHESIS_BY_ID = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id})
WHERE h.silo_id = $silo_id
RETURN h.id AS id,
       h.content AS content,
       h.confidence AS confidence,
       h.crystallized AS crystallized,
       h.state AS state
"""

GET_HYPOTHESIS_ABOUT_REFS = """
MATCH (h:WorkingHypothesis {id: $hypothesis_id, silo_id: $silo_id})-[:ABOUT]->(a)
RETURN a.id AS id, a.properties.state AS state
"""

CREATE_CRYSTALLIZED_FROM_EDGE = """
MATCH (commitment {id: $commitment_id, silo_id: $silo_id})
MATCH (hypothesis {id: $hypothesis_id, silo_id: $silo_id})
SET hypothesis.crystallized = true,
    hypothesis.crystallized_into = $commitment_id
CREATE (commitment)-[:CRYSTALLIZED_FROM {created_at: $created_at}]->(hypothesis)
RETURN commitment.id AS id
"""

# TX4 SYNTHESIZE and TX5 REVISE_BELIEF queries

# DEPRECATED (CITE v2): Cluster-based synthesis locking removed with :Cluster.
# Synthesis in v2 operates on Facts directly; no cluster lock needed.
# GET_CLUSTER_FOR_SYNTHESIS, RELEASE_CLUSTER_LOCK, UPDATE_CLUSTER_AFTER_SYNTHESIS
# — all removed

CREATE_BELIEF_WITH_SYNTHESIZED_FROM = """
CREATE (b:Belief {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    created_at: $created_at,
    properties: $props
})
WITH b
UNWIND $fact_ids AS fid
MATCH (f {id: fid, silo_id: $silo_id})
CREATE (b)-[:SYNTHESIZED_FROM]->(f)
RETURN b.id AS id
"""

GET_BELIEF_FOR_REVISION = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
RETURN b.id AS id,
       b.content AS content,
       b.properties.state AS state,
       b.properties.synthesis_state AS synthesis_state,
       b.properties.source_cluster_id AS source_cluster_id,
       b.properties.revision_in_progress AS revision_in_progress,
       b.properties.confidence AS confidence
"""

MARK_BELIEF_REVISION_IN_PROGRESS = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.properties.revision_in_progress = true
RETURN b.id AS id
"""

UPDATE_BELIEF_AFTER_REVISION = """
MATCH (b:Belief {id: $belief_id, silo_id: $silo_id})
SET b.properties.synthesis_state = $synthesis_state,
    b.properties.revision_in_progress = false
RETURN b.id AS id
"""

# TX15 FORGET (soft-delete with cancel window) and TX16 CANCEL_FORGET (restore)

TOMBSTONE_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state IN ['ACTIVE', 'SUPERSEDED']
SET n.properties.state = 'TOMBSTONED',
    n.properties.tombstoned_at = $tombstoned_at,
    n.properties.forget_requested_at = $forget_requested_at,
    n.properties.forget_requested_by = $agent_id,
    n.properties.forget_reason = $reason,
    n.properties.cancel_window_expires = $cancel_window_expires,
    n.properties.previous_state = n.properties.state
RETURN n.id AS id, n.properties.state AS state
"""

RESTORE_TOMBSTONED_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
  AND n.properties.cancel_window_expires > $now
SET n.properties.state = n.properties.previous_state,
    n.properties.tombstoned_at = null,
    n.properties.forget_requested_at = null,
    n.properties.forget_requested_by = null,
    n.properties.forget_reason = null,
    n.properties.cancel_window_expires = null,
    n.properties.restored_at = $restored_at,
    n.properties.restored_by = $agent_id
RETURN n.id AS id, n.properties.state AS state, n.properties.previous_state AS previous_state
"""

GET_NODE_FOR_FORGET = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.id AS id,
       n.properties.state AS state,
       n.properties.layer AS layer,
       n.type AS node_type,
       n.properties.cancel_window_expires AS cancel_window_expires
"""

# CASCADE_STALENESS and TX10 HARD_DELETE

GET_DEPENDENTS_FOR_CASCADE = """
MATCH (d)-[e:SYNTHESIZED_FROM|DERIVED_FROM]->(changed {id: $node_id, silo_id: $silo_id})
WHERE d.properties.state = 'ACTIVE'
RETURN d.id AS id, d.properties.layer AS layer, type(e) AS edge_type
"""

MARK_BELIEF_STALE_FOR_CASCADE = """
MATCH (b {id: $node_id, silo_id: $silo_id})
WHERE b.properties.layer = 'wisdom'
SET b.properties.synthesis_state = 'STALE'
RETURN b.id AS id
"""

GET_TOMBSTONED_FOR_GC = """
MATCH (n {silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
  AND n.properties.cancel_window_expires < $now
RETURN n.id AS id
LIMIT $batch_size
"""

DELETE_EDGES_FOR_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})-[e]-()
DELETE e
RETURN count(e) AS deleted_count
"""

HARD_DELETE_NODE = """
MATCH (n {id: $node_id, silo_id: $silo_id})
WHERE n.properties.state = 'TOMBSTONED'
DELETE n
RETURN count(n) AS deleted_count
"""

# TX18 PROMOTE and TX19 DEMOTE (layer movement)

GET_CLAIM_FOR_PROMOTE = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
RETURN c.id AS id,
       c.properties.state AS state,
       c.properties.claim_status AS claim_status,
       c.properties.corroboration_count AS corroboration_count,
       c.properties.confidence AS confidence
"""

UPDATE_CLAIM_TO_PROMOTED = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
WHERE c.properties.state = 'ACTIVE'
  AND c.properties.claim_status = 'UNPROMOTED'
SET c.properties.claim_status = 'PROMOTED',
    c.properties.promoted_at = $promoted_at,
    c.properties.confidence = $new_confidence
SET c:Fact
RETURN c.id AS id, c.properties.claim_status AS claim_status
"""

GET_FACT_FOR_DEMOTE = """
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
RETURN f.id AS id,
       f.properties.state AS state,
       f.properties.claim_status AS claim_status,
       f.properties.corroboration_count AS corroboration_count,
       f.properties.confidence AS confidence
"""

UPDATE_FACT_TO_DEMOTED = """
MATCH (f:Fact {id: $fact_id, silo_id: $silo_id})
WHERE f.properties.state = 'ACTIVE'
  AND f.properties.claim_status = 'PROMOTED'
SET f.properties.claim_status = 'UNPROMOTED',
    f.properties.demoted_at = $demoted_at,
    f.properties.confidence = $new_confidence
REMOVE f:Fact
RETURN f.id AS id, f.properties.claim_status AS claim_status
"""

RECOUNT_CORROBORATION = """
MATCH (c:Claim {id: $claim_id, silo_id: $silo_id})
MATCH (corroborating:Claim {silo_id: $silo_id})
WHERE corroborating.properties.subject = c.properties.subject
  AND corroborating.properties.predicate = c.properties.predicate
  AND corroborating.properties.object = c.properties.object
  AND corroborating.properties.state = 'ACTIVE'
OPTIONAL MATCH (corroborating)-[:DERIVED_FROM]->(evidence)
RETURN count(DISTINCT evidence.id) AS corroboration_count
"""

# --- Epistemology: confidence propagation queries ---

GET_SUPPORT_EDGES = """
MATCH (source {silo_id: $silo_id})-[e:SUPPORTS]->(target {silo_id: $silo_id})
WHERE source.properties.state = 'ACTIVE' AND target.properties.state = 'ACTIVE'
RETURN source.id AS source_id,
       target.id AS target_id,
       coalesce(e.weight, 1.0) AS weight
"""

GET_CONTRADICTION_EDGES = """
MATCH (source {silo_id: $silo_id})-[e:CONTRADICTS]->(target {silo_id: $silo_id})
WHERE source.properties.state = 'ACTIVE' AND target.properties.state = 'ACTIVE'
RETURN source.id AS source_id,
       target.id AS target_id,
       coalesce(e.weight, 1.0) AS weight
"""

GET_GRAPH_FOR_PROPAGATION = """
MATCH (n {silo_id: $silo_id})
WHERE n.properties.state = 'ACTIVE'
  AND n.properties.layer IN ['knowledge', 'wisdom']
WITH collect({
    id: n.id,
    credibility: coalesce(n.credibility, n.confidence, 0.5),
    layer: n.properties.layer
}) AS nodes
OPTIONAL MATCH (s {silo_id: $silo_id})-[sup:SUPPORTS]->(t {silo_id: $silo_id})
WHERE s.properties.state = 'ACTIVE' AND t.properties.state = 'ACTIVE'
WITH nodes, collect({source: s.id, target: t.id, weight: coalesce(sup.weight, 1.0)}) AS supports
OPTIONAL MATCH (s2 {silo_id: $silo_id})-[con:CONTRADICTS]->(t2 {silo_id: $silo_id})
WHERE s2.properties.state = 'ACTIVE' AND t2.properties.state = 'ACTIVE'
RETURN nodes,
       supports,
       collect({source: s2.id, target: t2.id, weight: coalesce(con.weight, 1.0)}) AS contradictions
"""

CREATE_WEIGHTED_SUPPORT_EDGE = """
MATCH (source {id: $source_id, silo_id: $silo_id})
MATCH (target {id: $target_id, silo_id: $silo_id})
MERGE (source)-[e:SUPPORTS]->(target)
ON CREATE SET e.weight = $weight, e.created_at = $created_at
ON MATCH SET e.weight = $weight
RETURN source.id AS source_id, target.id AS target_id, e.weight AS weight
"""

CREATE_WEIGHTED_CONTRADICTION_EDGE = """
MATCH (source {id: $source_id, silo_id: $silo_id})
MATCH (target {id: $target_id, silo_id: $silo_id})
MERGE (source)-[e:CONTRADICTS]->(target)
ON CREATE SET e.weight = $weight, e.created_at = $created_at
ON MATCH SET e.weight = $weight
RETURN source.id AS source_id, target.id AS target_id, e.weight AS weight
"""

UPDATE_PROPAGATED_CONFIDENCE = """
UNWIND $updates AS u
MATCH (n {id: u.node_id, silo_id: $silo_id})
SET n.confidence = u.confidence,
    n.confidence_updated_at = $updated_at
RETURN count(*) AS updated_count
"""

GET_LOCAL_GRAPH_FOR_PROPAGATION = """
MATCH path = (center {id: $node_id, silo_id: $silo_id})-[*..2]-(neighbor {silo_id: $silo_id})
WHERE neighbor.properties.state = 'ACTIVE'
WITH collect(DISTINCT center) + collect(DISTINCT neighbor) AS all_nodes
UNWIND all_nodes AS n
WITH collect(DISTINCT {id: n.id, credibility: coalesce(n.credibility, n.confidence, 0.5)}) AS nodes
OPTIONAL MATCH (s {silo_id: $silo_id})-[sup:SUPPORTS]->(t {silo_id: $silo_id})
WHERE s.id IN [node IN nodes | node.id] AND t.id IN [node IN nodes | node.id]
WITH nodes, collect({source: s.id, target: t.id, weight: coalesce(sup.weight, 1.0)}) AS supports
OPTIONAL MATCH (s2 {silo_id: $silo_id})-[con:CONTRADICTS]->(t2 {silo_id: $silo_id})
WHERE s2.id IN [node IN nodes | node.id] AND t2.id IN [node IN nodes | node.id]
RETURN nodes,
       supports,
       collect({source: s2.id, target: t2.id, weight: coalesce(con.weight, 1.0)}) AS contradictions
"""
