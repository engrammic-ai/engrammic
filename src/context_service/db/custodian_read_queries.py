"""Read-only Cypher for Custodian tool implementations.

DEPRECATED (CITE v2): Clustering removed in v2 schema. All cluster-related
queries return empty results. Module retained for backwards compatibility with
callers that haven't been updated yet.

TODO: Remove entire module after all callers are updated to v2 APIs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.db.schema import content_union_predicate

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

# Unused import but retained for API compat with any callers that reference it
_cup = content_union_predicate


# ---------------------------------------------------------------------------
# Stub queries (v2: clustering removed, all return empty results)
# ---------------------------------------------------------------------------

FETCH_CLUSTER_MEMBERS = "RETURN null AS node_id, null AS content, null AS silo_id, null AS label LIMIT 0"
COUNT_CLUSTER_MEMBERS = "RETURN 0 AS total"
FETCH_NODE_BY_ID = "RETURN null AS node_id, null AS content, null AS silo_id, null AS label LIMIT 0"
FETCH_NEIGHBORHOOD_SEED = "RETURN null AS seed_id, null AS seed_content, null AS silo_id, null AS label LIMIT 0"
FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE = "RETURN null AS node_id, null AS content, null AS silo_id, null AS label LIMIT 0"
LIST_EDGES_OF_TYPE_IN_CLUSTER = "RETURN null AS edge_id, null AS edge_type, null AS source_id, null AS target_id LIMIT 0"
FETCH_LOWER_FINDINGS = "RETURN null LIMIT 0"
FETCH_CLUSTER_MEMBER_IDS = "RETURN null AS node_id LIMIT 0"


# ---------------------------------------------------------------------------
# Async helpers — stubbed to return empty results (v2: clustering removed)
# TODO: Remove entire module after all callers are updated to v2 APIs.
# ---------------------------------------------------------------------------


async def fetch_cluster_members(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
    limit: int,  # noqa: ARG001
    offset: int,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    return []


async def count_cluster_members(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> int:
    """DEPRECATED (CITE v2): Clustering removed. Returns 0."""
    return 0


async def fetch_node_by_id(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    node_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> dict[str, Any] | None:
    """DEPRECATED (CITE v2): Clustering removed. Returns None."""
    return None


async def fetch_neighborhood(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    node_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
    depth: int = 1,  # noqa: ARG001
) -> dict[str, Any] | None:
    """DEPRECATED (CITE v2): Clustering removed. Returns None."""
    return None


async def list_edges_of_type_in_cluster(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    cluster_id: str,  # noqa: ARG001
    edge_type: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    return []


async def fetch_lower_findings(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    parent_cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    return []


async def fetch_cluster_member_ids(
    client: HyperGraphStore,  # noqa: ARG001
    *,
    cluster_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
) -> list[str]:
    """DEPRECATED (CITE v2): Clustering removed. Returns empty list."""
    return []


__all__ = [
    "COUNT_CLUSTER_MEMBERS",
    "FETCH_CLUSTER_MEMBERS",
    "FETCH_CLUSTER_MEMBER_IDS",
    "FETCH_LOWER_FINDINGS",
    "FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE",
    "FETCH_NEIGHBORHOOD_SEED",
    "FETCH_NODE_BY_ID",
    "LIST_EDGES_OF_TYPE_IN_CLUSTER",
    "count_cluster_members",
    "fetch_cluster_member_ids",
    "fetch_cluster_members",
    "fetch_lower_findings",
    "fetch_neighborhood",
    "fetch_node_by_id",
    "list_edges_of_type_in_cluster",
]
