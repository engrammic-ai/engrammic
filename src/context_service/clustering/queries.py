"""Clustering-specific Cypher query templates for Memgraph.

All queries use parameterized values for safety and are silo-scoped.
"""

from primitives.eag.queries.cluster import (
    BATCH_CREATE_MEMBER_OF,
    BATCH_UPDATE_NODE_IMPORTANCE,
    COUNT_CLUSTERS,
    CREATE_CLUSTER,
    CREATE_PART_OF,
    DELETE_CLUSTERS,
    GET_CLUSTER,
    GET_CLUSTER_MEMBERS,
    GET_CLUSTER_PARENT,
    GET_NODE_CLUSTERS,
    LIST_CLUSTERS,
    RUN_LEIDEN,
    RUN_PAGERANK,
    UPDATE_CLUSTER_SUMMARY,
)

# R-006: one round-trip for all Cluster nodes in a level (replaces per-cluster CREATE_CLUSTER loop).
BATCH_CREATE_CLUSTERS = """
UNWIND $clusters AS c
CREATE (:Cluster {
    id: c.id,
    silo_id: $silo_id,
    level: c.level,
    community_id: c.community_id,
    summary: null,
    key_topics: c.key_topics,
    node_count: c.node_count,
    created_at: $created_at,
    updated_at: $updated_at
})
RETURN count(*) AS created
"""

__all__ = [
    "BATCH_CREATE_CLUSTERS",
    "BATCH_CREATE_MEMBER_OF",
    "BATCH_UPDATE_NODE_IMPORTANCE",
    "COUNT_CLUSTERS",
    "CREATE_CLUSTER",
    "CREATE_PART_OF",
    "DELETE_CLUSTERS",
    "GET_CLUSTER",
    "GET_CLUSTER_MEMBERS",
    "GET_CLUSTER_PARENT",
    "GET_NODE_CLUSTERS",
    "LIST_CLUSTERS",
    "RUN_LEIDEN",
    "RUN_PAGERANK",
    "UPDATE_CLUSTER_SUMMARY",
]
