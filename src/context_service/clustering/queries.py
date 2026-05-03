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
from primitives.protocols import Layer

from context_service.db.queries import (
    BATCH_CREATE_PART_OF,
    BATCH_UPDATE_CLUSTER_SUMMARIES,
    DELETE_ALL_CLUSTERS,
)

# ---------------------------------------------------------------------------
# Layer scoping helpers
# ---------------------------------------------------------------------------

_LAYER_LABEL_MAP: dict[Layer, list[str]] = {
    Layer.MEMORY: ["Document", "Passage"],
    Layer.KNOWLEDGE: ["Fact", "Claim"],
}

_UNSUPPORTED_LAYERS = {Layer.WISDOM, Layer.INTELLIGENCE}


def layer_label_list(layers: list[Layer]) -> list[str]:
    """Return flat list of label strings for the given layers.

    e.g. layer_label_list([Layer.KNOWLEDGE]) -> ["Fact", "Claim"]

    Only MEMORY and KNOWLEDGE are supported. Raises ValueError for empty input,
    WISDOM, or INTELLIGENCE.
    """
    if not layers:
        raise ValueError("layers must not be empty")
    unsupported = set(layers) & _UNSUPPORTED_LAYERS
    if unsupported:
        names = ", ".join(layer.value.capitalize() for layer in unsupported)
        raise ValueError(f"Unsupported layers for clustering: {names}")
    return [label for layer in layers for label in _LAYER_LABEL_MAP[layer]]


def layer_labels(layers: list[Layer]) -> str:
    """Return a Cypher label-predicate string for the given layers.

    e.g. layer_labels([Layer.KNOWLEDGE]) -> "Fact OR Claim"

    Only MEMORY and KNOWLEDGE are supported. Raises ValueError for empty input,
    WISDOM, or INTELLIGENCE because those layers have no content nodes that are
    clusterable at this time.
    """
    return " OR ".join(layer_label_list(layers))


# Scoped variants — accept $node_labels as a Cypher list param.
# node_labels: list[str], e.g. ["Fact", "Claim"]

RUN_LEIDEN_SCOPED = """
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND any(lbl IN $node_labels WHERE lbl IN labels(node))
RETURN node.id AS node_id, community_id
"""

BATCH_CREATE_MEMBER_OF_SCOPED = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
UNWIND $node_ids AS nid
MATCH (n {id: nid})
WHERE any(lbl IN $node_labels WHERE lbl IN labels(n))
CREATE (n)-[:MEMBER_OF {weight: $weight, created_at: $created_at}]->(c)
RETURN count(*) as created
"""

RUN_PAGERANK_SCOPED = """
CALL pagerank.get()
YIELD node, rank
WITH node, rank
WHERE any(lbl IN $node_labels WHERE lbl IN labels(node))
  AND node.silo_id = $silo_id
RETURN node.id AS node_id, rank
"""

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
    "BATCH_CREATE_MEMBER_OF_SCOPED",
    "BATCH_CREATE_PART_OF",
    "BATCH_UPDATE_CLUSTER_SUMMARIES",
    "BATCH_UPDATE_NODE_IMPORTANCE",
    "COUNT_CLUSTERS",
    "CREATE_CLUSTER",
    "CREATE_PART_OF",
    "DELETE_ALL_CLUSTERS",
    "DELETE_CLUSTERS",
    "GET_CLUSTER",
    "GET_CLUSTER_MEMBERS",
    "GET_CLUSTER_PARENT",
    "GET_NODE_CLUSTERS",
    "LIST_CLUSTERS",
    "RUN_LEIDEN",
    "RUN_LEIDEN_SCOPED",
    "RUN_PAGERANK",
    "RUN_PAGERANK_SCOPED",
    "UPDATE_CLUSTER_SUMMARY",
    "layer_label_list",
    "layer_labels",
]
