"""Read-only Cypher for Custodian tool implementations (Task 8).

Separate from ``context_service/db/custodian_queries.py`` (Task 6's write-path
module) so parallel branches do not touch the same file. Every query here is
read-only and tenant/silo scoped; callers pass the scope via parameters.

Phase-3 label change: content nodes use Document|Passage|Claim labels (O-30),
not the legacy :Node label. Retrieval-facing reads additionally filter
``n.committed = true`` per O-75. FETCH_NODE_BY_ID omits the committed filter
because it is called from the Custodian write-path audit context (the Custodian
may legitimately visit nodes that are mid-ingest; committed=false nodes are
valid targets during a Custodian pass).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from context_service.db.schema import content_union_predicate

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.stores.memgraph import MemgraphClient

_cup = content_union_predicate


# ---------------------------------------------------------------------------
# Cypher constants
# ---------------------------------------------------------------------------


# Return core-content members of a cluster, silo-scoped, paginated.
# committed=true filter per O-75; Custodian visits only committed nodes.
FETCH_CLUSTER_MEMBERS = f"""
MATCH (n)-[:MEMBER_OF]->(c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
WHERE {_cup("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
RETURN n.id AS node_id,
       n.content AS content,
       n.silo_id AS silo_id,
       labels(n)[0] AS label
ORDER BY n.id
SKIP $offset
LIMIT $limit
"""


# Count committed core-content members of a cluster (for has_more / total).
COUNT_CLUSTER_MEMBERS = f"""
MATCH (n)-[:MEMBER_OF]->(c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
WHERE {_cup("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
RETURN count(n) AS total
"""


# Single content-node lookup, silo-scoped. No committed=true filter here:
# this is called from the Custodian audit write-path which may visit nodes
# that are still mid-ingest (committed=false is a valid Custodian target).
FETCH_NODE_BY_ID = f"""
MATCH (n {{id: $node_id, silo_id: $silo_id}})
WHERE {_cup("n")}
RETURN n.id AS node_id,
       n.content AS content,
       n.silo_id AS silo_id,
       labels(n)[0] AS label
LIMIT 1
"""


# One-hop (depth-parameterised) neighbourhood around a seed node. Mirrors the
# pattern in ``context_service/engine/queries.NEIGHBORHOOD``. ``$depth`` is
# interpolated via Python str formatting since Memgraph's Cypher does not
# accept parameterised variable-length bounds -- callers MUST pass an int,
# and the helper below enforces bounds. Two-statement shape: fetch seed row,
# then fetch neighbours with their deduped distance. This avoids subtle
# collect() interactions with variable-length path list variables that drop
# rows in Memgraph. committed=true on seed per O-75; neighbourhood is
# retrieval-facing.
FETCH_NEIGHBORHOOD_SEED = f"""
MATCH (start {{id: $node_id, silo_id: $silo_id}})
WHERE {_cup("start")}
  AND start.committed = true
RETURN start.id AS seed_id,
       start.content AS seed_content,
       start.silo_id AS silo_id,
       labels(start)[0] AS label
LIMIT 1
"""

# Variable-length path template: edge type drives traversal, not node label.
# committed=true on neighbours per O-75.
FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE = f"""
MATCH (start {{{{id: $node_id, silo_id: $silo_id}}}})
WHERE {_cup("start")}
MATCH (start)-[:EDGE*1..{{depth}}]-(other)
WHERE {_cup("other")}
  AND other.silo_id = $silo_id
  AND other.id <> start.id
  AND other.committed = true
RETURN DISTINCT other.id AS node_id,
                other.content AS content,
                other.silo_id AS silo_id,
                labels(other)[0] AS label
"""

# Kept for back-compat with the public import surface; equals the neighbours
# template string so external callers pinning it by reference still resolve.
FETCH_NEIGHBORHOOD_TEMPLATE = FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE


# List edges of a given type inside a cluster. Both endpoints must be cluster
# members. ``$edge_type`` filters on ``e.type`` (the free-form property set by
# extraction); the relationship label itself is the generic ``:EDGE``.
# committed=true on both endpoints per O-75 (retrieval-facing query).
LIST_EDGES_OF_TYPE_IN_CLUSTER = f"""
MATCH (a)-[:MEMBER_OF]->(c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
MATCH (b)-[:MEMBER_OF]->(c)
MATCH (a)-[e:EDGE]->(b)
WHERE e.type = $edge_type
  AND {_cup("a")}
  AND {_cup("b")}
  AND a.silo_id = $silo_id
  AND b.silo_id = $silo_id
  AND a.committed = true
  AND b.committed = true
RETURN e.id AS edge_id,
       e.type AS edge_type,
       a.id AS source_id,
       b.id AS target_id
ORDER BY e.id
"""


# Child findings of a parent cluster. "Child" means: a :Finding attached via
# :ABOUT to a :Cluster whose :PART_OF edge points at the parent cluster.
# member_fingerprint and claims are returned so the client can apply the
# fingerprint-drift filter before handing results to the agent.
FETCH_LOWER_FINDINGS = """
MATCH (parent:Cluster {id: $parent_cluster_id, silo_id: $silo_id})
MATCH (child:Cluster)-[:PART_OF]->(parent)
WHERE child.silo_id = $silo_id
MATCH (f:Finding {scope: "cluster", silo_id: $silo_id})-[:ABOUT]->(child)
WHERE (f.source = 'extraction' OR f.status = 'published')
RETURN f.id AS finding_id,
       child.id AS child_cluster_id,
       f.claims AS claims_json,
       f.summary AS summary_json,
       f.member_fingerprint AS member_fingerprint,
       f.quality_score AS quality_score,
       f.version AS version
ORDER BY f.id
"""


# Member node_ids for fingerprint comparison. committed=true per O-75.
FETCH_CLUSTER_MEMBER_IDS = f"""
MATCH (n)-[:MEMBER_OF]->(c:Cluster {{id: $cluster_id, silo_id: $silo_id}})
WHERE {_cup("n")}
  AND n.silo_id = $silo_id
  AND n.committed = true
RETURN n.id AS node_id
"""


# ---------------------------------------------------------------------------
# Async helpers -- thin wrappers around MemgraphClient.execute_query
# ---------------------------------------------------------------------------


async def fetch_cluster_members(
    client: MemgraphClient,
    *,
    cluster_id: str,
    silo_id: str,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Return :Node rows for a cluster slice."""
    return await client.execute_query(
        FETCH_CLUSTER_MEMBERS,
        {
            "cluster_id": cluster_id,
            "silo_id": silo_id,
            "limit": int(limit),
            "offset": int(offset),
        },
    )


async def count_cluster_members(
    client: MemgraphClient,
    *,
    cluster_id: str,
    silo_id: str,
) -> int:
    rows = await client.execute_query(
        COUNT_CLUSTER_MEMBERS,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )
    if not rows:
        return 0
    return int(rows[0]["total"])


async def fetch_node_by_id(
    client: MemgraphClient,
    *,
    node_id: str,
    silo_id: str,
) -> dict[str, Any] | None:
    rows = await client.execute_query(
        FETCH_NODE_BY_ID,
        {"node_id": node_id, "silo_id": silo_id},
    )
    return rows[0] if rows else None


async def fetch_neighborhood(
    client: MemgraphClient,
    *,
    node_id: str,
    silo_id: str,
    depth: int = 1,
) -> dict[str, Any] | None:
    """Return the seed node + one-hop neighbours (bounded by ``depth``).

    Two-statement shape: the seed lookup and neighbour lookup run as separate
    Cypher queries because Memgraph's handling of ``collect()`` over
    variable-length path edge variables is fragile. Returns ``None`` when the
    seed does not exist; otherwise a dict with the seed fields plus a
    ``neighbours`` list.
    """
    if not isinstance(depth, int) or depth < 1 or depth > 3:
        raise ValueError(f"depth must be an int in [1, 3]; got {depth!r}")

    seed_rows = await client.execute_query(
        FETCH_NEIGHBORHOOD_SEED,
        {"node_id": node_id, "silo_id": silo_id},
    )
    if not seed_rows:
        return None

    neighbour_query = FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE.format(depth=depth)
    neighbour_rows = await client.execute_query(
        neighbour_query,
        {"node_id": node_id, "silo_id": silo_id},
    )

    seed = seed_rows[0]
    return {
        "seed_id": seed["seed_id"],
        "seed_content": seed["seed_content"],
        "silo_id": seed["silo_id"],
        "neighbours": neighbour_rows,
    }


async def list_edges_of_type_in_cluster(
    client: MemgraphClient,
    *,
    cluster_id: str,
    edge_type: str,
    silo_id: str,
) -> list[dict[str, Any]]:
    return await client.execute_query(
        LIST_EDGES_OF_TYPE_IN_CLUSTER,
        {
            "cluster_id": cluster_id,
            "edge_type": edge_type,
            "silo_id": silo_id,
        },
    )


async def fetch_lower_findings(
    client: MemgraphClient,
    *,
    parent_cluster_id: str,
    silo_id: str,
) -> list[dict[str, Any]]:
    return await client.execute_query(
        FETCH_LOWER_FINDINGS,
        {
            "parent_cluster_id": parent_cluster_id,
            "silo_id": silo_id,
        },
    )


async def fetch_cluster_member_ids(
    client: MemgraphClient | HyperGraphStore,
    *,
    cluster_id: str,
    silo_id: str,
) -> list[str]:
    rows = await client.execute_query(
        FETCH_CLUSTER_MEMBER_IDS,
        {"cluster_id": cluster_id, "silo_id": silo_id},
    )
    return [row["node_id"] for row in rows]


__all__ = [
    "COUNT_CLUSTER_MEMBERS",
    "FETCH_CLUSTER_MEMBERS",
    "FETCH_CLUSTER_MEMBER_IDS",
    "FETCH_LOWER_FINDINGS",
    "FETCH_NEIGHBORHOOD_NEIGHBOURS_TEMPLATE",
    "FETCH_NEIGHBORHOOD_SEED",
    "FETCH_NEIGHBORHOOD_TEMPLATE",
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
