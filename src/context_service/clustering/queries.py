"""Clustering-specific Cypher query templates for Memgraph.

All queries use parameterized values for safety and are silo-scoped.
"""

from context_service.db.schema import LABEL_ENTITY, content_union_predicate

# --- Index creation ---

CREATE_CLUSTER_ID_INDEX = "CREATE INDEX ON :Cluster(id);"
CREATE_CLUSTER_LEVEL_INDEX = "CREATE INDEX ON :Cluster(level);"
CREATE_CLUSTER_SILO_INDEX = "CREATE INDEX ON :Cluster(silo_id);"

# --- Cluster CRUD ---

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

UPDATE_CLUSTER_SUMMARY = """
MATCH (c:Cluster {id: $id, silo_id: $silo_id})
SET c.summary = $summary, c.key_topics = $key_topics, c.updated_at = $updated_at
RETURN c
"""

# --- Cluster membership ---
#
# Edge label: MEMBER_OF (CAGEdgeType.MEMBER_OF from primitives.schema.edges).
# The source graph uses BELONGS_TO; context-service uses MEMBER_OF per the CAG
# edge schema. PART_OF is not in CAGEdgeType — it remains a plain string label
# for the inter-cluster hierarchy relationship (child cluster -> parent cluster).

BATCH_CREATE_BELONGS_TO = f"""
MATCH (c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
UNWIND $node_ids AS nid
MATCH (n {{id: nid}})
WHERE {content_union_predicate("n")} OR n:{LABEL_ENTITY}
CREATE (n)-[:MEMBER_OF {{weight: $weight, created_at: $created_at}}]->(c)
RETURN count(*) as created
"""

CREATE_PART_OF = """
MATCH (child:Cluster {id: $child_id, silo_id: $silo_id})
MATCH (parent:Cluster {id: $parent_id, silo_id: $silo_id})
CREATE (child)-[r:PART_OF {created_at: $created_at}]->(parent)
RETURN r
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

# --- Community detection via Memgraph MAGE ---
#
# We use igraphalg.community_leiden (igraph's Leiden) instead of MAGE's native
# leiden_community_detection.get because the native implementation raises
# "No communities detected" on our graph at every resolution value. igraph
# Leiden handles the same graph fine and is algorithmically equivalent.
#
# Silo filtering is applied post-detection by restricting to nodes with the
# matching silo_id. Resolution (gamma) controls community granularity:
# FINE=0.1, MEDIUM=0.01, COARSE=0.001.
RUN_LEIDEN = f"""
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND ({content_union_predicate("node")} OR node:{LABEL_ENTITY})
RETURN node.id AS node_id, community_id
"""

# --- PageRank ---
#
# PageRank runs on the whole graph; silo filter is applied on results.
# Importance applies to Document, Passage, Claim, and Entity nodes.
RUN_PAGERANK = f"""
CALL pagerank.get()
YIELD node, rank
WITH node, rank
WHERE ({content_union_predicate("node")} OR node:{LABEL_ENTITY})
  AND node.silo_id = $silo_id
RETURN node.id AS node_id, rank
"""

BATCH_UPDATE_NODE_IMPORTANCE = f"""
UNWIND $updates AS u
MATCH (n {{id: u.node_id, silo_id: $silo_id}})
WHERE {content_union_predicate("n")} OR n:{LABEL_ENTITY}
SET n.importance = u.rank
RETURN count(n) as updated
"""
