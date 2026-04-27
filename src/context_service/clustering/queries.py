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

__all__ = [
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

# --- Index creation ---

CREATE_CLUSTER_ID_INDEX = "CREATE INDEX ON :Cluster(id);"
CREATE_CLUSTER_LEVEL_INDEX = "CREATE INDEX ON :Cluster(level);"
CREATE_CLUSTER_SILO_INDEX = "CREATE INDEX ON :Cluster(silo_id);"
