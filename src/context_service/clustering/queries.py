"""Clustering-specific Cypher query templates for Memgraph.

DEPRECATED (CITE v2): Clustering removed in v2 schema. All queries return empty
results. Module retained for backwards compatibility with callers that haven't
been updated yet.

TODO: Remove entire module after all callers are updated to v2 APIs.
"""

from primitives.protocols import Layer

# ---------------------------------------------------------------------------
# Stub queries (v2: clustering removed)
# ---------------------------------------------------------------------------

BATCH_CREATE_MEMBER_OF = "RETURN 0 AS created"
BATCH_UPDATE_NODE_IMPORTANCE = "RETURN 0 AS updated"
COUNT_CLUSTERS = "RETURN 0 AS count"
CREATE_CLUSTER = "RETURN null AS cluster_id LIMIT 0"
CREATE_PART_OF = "RETURN null LIMIT 0"
DELETE_CLUSTERS = "RETURN 0 AS deleted"
GET_CLUSTER = "RETURN null LIMIT 0"
GET_CLUSTER_MEMBERS = "RETURN null LIMIT 0"
GET_CLUSTER_PARENT = "RETURN null LIMIT 0"
GET_NODE_CLUSTERS = "RETURN null LIMIT 0"
LIST_CLUSTERS = "RETURN null LIMIT 0"
RUN_LEIDEN = "RETURN null LIMIT 0"
RUN_PAGERANK = "RETURN null LIMIT 0"
UPDATE_CLUSTER_SUMMARY = "RETURN null LIMIT 0"

# Re-export stubs from db.queries for callers that import from here
BATCH_CREATE_PART_OF = "RETURN 0 AS created_count"
BATCH_UPDATE_CLUSTER_SUMMARIES = "RETURN 0 AS updated_count"
DELETE_ALL_CLUSTERS = "RETURN 0 AS deleted_count"

# ---------------------------------------------------------------------------
# Layer scoping helpers (v2: Memory replaces Document/Passage)
# ---------------------------------------------------------------------------

_LAYER_LABEL_MAP: dict[Layer, list[str]] = {
    Layer.MEMORY: ["Memory"],
    Layer.KNOWLEDGE: ["Fact", "Claim"],
}

_UNSUPPORTED_LAYERS = {Layer.WISDOM, Layer.INTELLIGENCE}


def layer_label_list(layers: list[Layer]) -> list[str]:
    """Return flat list of label strings for the given layers.

    DEPRECATED (CITE v2): Clustering removed. Returns v2 labels for compat.
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

    DEPRECATED (CITE v2): Clustering removed. Returns v2 labels for compat.
    """
    return " OR ".join(layer_label_list(layers))


# ---------------------------------------------------------------------------
# Scoped variants — stubbed (v2: clustering removed)
# ---------------------------------------------------------------------------

RUN_LEIDEN_SCOPED = "RETURN null AS node_id, null AS community_id LIMIT 0"
BATCH_CREATE_MEMBER_OF_SCOPED = "RETURN 0 AS created"
RUN_PAGERANK_SCOPED = "RETURN null AS node_id, null AS rank LIMIT 0"
BATCH_CREATE_CLUSTERS = "RETURN 0 AS created"

__all__ = [
    # Stub queries (v2: all return empty results)
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
    # Layer helpers (retained for compat)
    "layer_label_list",
    "layer_labels",
]
