"""Heat diffusion BFS algorithm and data models.

Implements a breadth-first heat propagation over a subgraph. Hot nodes seed
the BFS; heat decays at each hop according to DiffusionConfig parameters.

The database layer (fetch_hot_nodes, fetch_subgraph, batch_update_propagated_heat,
etc.) executes raw Cypher against a HyperGraphStore and is the primary I/O
boundary for the Dagster heat diffusion asset.
"""

from __future__ import annotations

import datetime
from collections import defaultdict, deque
from dataclasses import dataclass, field

import structlog

from context_service.config.diffusion import DiffusionConfig
from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Cypher query constants
# ---------------------------------------------------------------------------

FETCH_HOT_NODES_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.heat_score >= $hot_threshold
RETURN n.id AS id, n.heat_score AS heat_score
ORDER BY n.heat_score DESC
LIMIT $limit
"""

FETCH_SUBGRAPH_QUERY = """
MATCH (hot {{silo_id: $silo_id}})
WHERE hot.id IN $hot_node_ids
MATCH path = (hot)-[r*1..{max_depth}]-(neighbor)
WHERE neighbor.silo_id = $silo_id
UNWIND relationships(path) AS rel
WITH DISTINCT startNode(rel) AS src, endNode(rel) AS dst, rel
RETURN src.id AS source_id, dst.id AS target_id,
       type(rel) AS edge_type, rel.edge_heat AS edge_heat
"""

DECAY_PROPAGATED_HEAT_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.propagated_heat IS NOT NULL
SET n.propagated_heat = n.propagated_heat * $decay_factor
"""

UPDATE_PROPAGATED_HEAT_QUERY = """
UNWIND $updates AS u
MATCH (n {id: u.node_id, silo_id: $silo_id})
SET n.propagated_heat = u.propagated_heat,
    n.effective_heat = CASE
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat > 1.0 THEN 1.0
        ELSE coalesce(n.heat_score, 0) + u.propagated_heat
    END,
    n.materialization_level = CASE
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $full_threshold THEN 'FULL'
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $warm_threshold THEN 'WARM'
        WHEN coalesce(n.heat_score, 0) + u.propagated_heat >= $structure_threshold THEN 'STRUCTURE'
        ELSE 'MINIMAL'
    END,
    n.diffusion_updated_at = $now
"""

COUNT_MATERIALIZATION_LEVELS_QUERY = """
MATCH (n {silo_id: $silo_id})
WHERE n.materialization_level IS NOT NULL
RETURN n.materialization_level AS level, count(*) AS count
"""


@dataclass
class SubgraphEdge:
    """A directed edge in the diffusion subgraph.

    Attributes:
        source_id: ID of the originating node.
        target_id: ID of the destination node.
        edge_type: Relationship type label (e.g. "RELATED_TO").
        edge_heat: Optional heat weight carried by the edge itself.
            Treated as 0.5 when None (spec: ``edge.heat or 0.5``).
    """

    source_id: str
    target_id: str
    edge_type: str
    edge_heat: float | None


@dataclass
class HotNode:
    """A seed node for heat diffusion.

    Attributes:
        id: Node identifier.
        heat_score: Initial heat value in [0.0, 1.0].
    """

    id: str
    heat_score: float


@dataclass
class DiffusionResult:
    """Summary of a completed diffusion run.

    Attributes:
        hot_nodes: Number of seed (hot) nodes used in the run.
        nodes_updated: Number of nodes that received propagated heat.
        edge_traversals: Count of edges traversed per edge type.
        propagation_map: Mapping from node ID to its propagated heat score.
    """

    hot_nodes: int
    nodes_updated: int
    edge_traversals: dict[str, int]
    propagation_map: dict[str, float] = field(default_factory=dict)


def build_adjacency_list(edges: list[SubgraphEdge]) -> dict[str, list[SubgraphEdge]]:
    """Build a bidirectional adjacency list from a list of directed edges.

    Each edge is added in both the forward direction (source -> target) and
    the reverse direction (target -> source, with IDs swapped).

    Args:
        edges: Directed edges to index.

    Returns:
        Mapping from node ID to all adjacent SubgraphEdge entries (both
        forward and reverse). Nodes with no edges are omitted.
    """
    adj: dict[str, list[SubgraphEdge]] = defaultdict(list)
    for edge in edges:
        adj[edge.source_id].append(edge)
        reverse = SubgraphEdge(
            source_id=edge.target_id,
            target_id=edge.source_id,
            edge_type=edge.edge_type,
            edge_heat=edge.edge_heat,
        )
        adj[edge.target_id].append(reverse)
    return dict(adj)


def propagate_heat_bfs(
    hot_nodes: list[HotNode],
    adjacency: dict[str, list[SubgraphEdge]],
    config: DiffusionConfig,
) -> DiffusionResult:
    """Propagate heat from seed nodes via BFS across the adjacency graph.

    For each edge traversal the propagated heat is computed as::

        propagated = current_heat * hop_decay * edge_weight * edge_heat

    where ``edge_weight`` is looked up from ``config.edge_weights`` (defaulting
    to 0.4 for unknown types) and ``edge_heat`` defaults to 0.5 when None
    (spec: ``edge.heat or 0.5``).

    Note: ``propagated_heat_decay`` (a separate attenuation applied to seed
    node scores before BFS) is handled upstream in the Dagster asset layer.
    By the time ``hot_nodes`` reaches this function their heat scores already
    reflect that decay; this function only applies per-hop and per-edge
    factors.

    When multiple sources reach the same node, the maximum propagated value is
    retained. BFS is pruned when the propagated heat falls below
    ``config.min_threshold`` or the traversal depth exceeds ``config.max_depth``.

    Args:
        hot_nodes: Seed nodes with initial heat scores.
        adjacency: Bidirectional adjacency list (from :func:`build_adjacency_list`).
        config: Diffusion configuration parameters.

    Returns:
        :class:`DiffusionResult` summarising the run.
    """
    if not hot_nodes:
        return DiffusionResult(hot_nodes=0, nodes_updated=0, edge_traversals={})

    # Fallback weight for unrecognised edge types; intentionally mirrors the
    # RELATED_TO weight from the default DiffusionConfig.edge_weights.
    default_edge_weight = 0.4

    # propagation_map accumulates the best (max) heat for each non-seed node
    propagation_map: dict[str, float] = {}
    edge_traversals: dict[str, int] = defaultdict(int)

    # BFS queue entries: (node_id, current_heat, depth)
    queue: deque[tuple[str, float, int]] = deque()

    # Seed the queue with every hot node; treat them as visited at heat=score
    # so that they are not re-propagated via reverse edges into themselves.
    visited_heat: dict[str, float] = {}
    for node in hot_nodes:
        visited_heat[node.id] = node.heat_score
        queue.append((node.id, node.heat_score, 0))

    while queue:
        node_id, current_heat, depth = queue.popleft()

        if depth >= config.max_depth:
            continue

        for edge in adjacency.get(node_id, []):
            edge_weight = config.edge_weights.get(edge.edge_type, default_edge_weight)
            effective_edge_heat = edge.edge_heat if edge.edge_heat is not None else 0.5
            propagated = current_heat * config.hop_decay * edge_weight * effective_edge_heat

            if propagated < config.min_threshold:
                continue

            edge_traversals[edge.edge_type] += 1

            neighbor = edge.target_id
            prev_best = visited_heat.get(neighbor)
            if prev_best is None or propagated > prev_best:
                visited_heat[neighbor] = propagated
                propagation_map[neighbor] = propagated
                queue.append((neighbor, propagated, depth + 1))

    # Remove seed nodes from the propagation_map (they were not propagated to)
    seed_ids = {n.id for n in hot_nodes}
    for sid in seed_ids:
        propagation_map.pop(sid, None)

    return DiffusionResult(
        hot_nodes=len(hot_nodes),
        nodes_updated=len(propagation_map),
        edge_traversals=dict(edge_traversals),
        propagation_map=propagation_map,
    )


async def fetch_hot_nodes(
    store: HyperGraphStore,
    silo_id: str,
    hot_threshold: float,
    limit: int,
) -> list[HotNode]:
    """Fetch nodes with heat_score >= hot_threshold from the graph store.

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.
        hot_threshold: Minimum heat_score a node must have to be returned.
        limit: Maximum number of nodes to return.

    Returns:
        List of :class:`HotNode` ordered by descending heat_score.
    """
    log = logger.bind(silo_id=silo_id, hot_threshold=hot_threshold, limit=limit)
    rows = await store.execute_query(
        FETCH_HOT_NODES_QUERY,
        {"silo_id": silo_id, "hot_threshold": hot_threshold, "limit": limit},
    )
    nodes = [HotNode(id=row["id"], heat_score=row["heat_score"]) for row in rows]
    log.debug("fetch_hot_nodes.done", count=len(nodes))
    return nodes


async def fetch_subgraph(
    store: HyperGraphStore,
    silo_id: str,
    hot_node_ids: list[str],
    max_depth: int,
) -> list[SubgraphEdge]:
    """Fetch all edges within max_depth hops of the given hot nodes.

    The variable-length path pattern ``*1..{max_depth}`` is substituted
    at call time so Memgraph receives a concrete integer bound rather
    than a query parameter (Cypher does not support parameterised path
    lengths).

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.
        hot_node_ids: Node IDs to use as diffusion seeds.
        max_depth: Maximum hop depth for the path expansion.

    Returns:
        List of :class:`SubgraphEdge` covering all traversed relationships.
    """
    if not hot_node_ids:
        return []

    log = logger.bind(silo_id=silo_id, hot_node_count=len(hot_node_ids), max_depth=max_depth)
    query = FETCH_SUBGRAPH_QUERY.format(max_depth=max_depth)
    rows = await store.execute_query(
        query,
        {"silo_id": silo_id, "hot_node_ids": hot_node_ids},
    )
    edges = [
        SubgraphEdge(
            source_id=row["source_id"],
            target_id=row["target_id"],
            edge_type=row["edge_type"],
            edge_heat=row.get("edge_heat"),
        )
        for row in rows
    ]
    log.debug("fetch_subgraph.done", edge_count=len(edges))
    return edges


async def decay_propagated_heat(
    store: HyperGraphStore,
    silo_id: str,
    decay_factor: float,
) -> None:
    """Multiply every node's propagated_heat by decay_factor in-place.

    Nodes without a propagated_heat property are unaffected (the WHERE
    clause in the Cypher guards against NULL).

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.
        decay_factor: Multiplicative decay to apply; values in (0, 1) reduce heat.
    """
    log = logger.bind(silo_id=silo_id, decay_factor=decay_factor)
    await store.execute_write(
        DECAY_PROPAGATED_HEAT_QUERY,
        {"silo_id": silo_id, "decay_factor": decay_factor},
    )
    log.debug("decay_propagated_heat.done")


async def batch_update_propagated_heat(
    store: HyperGraphStore,
    silo_id: str,
    propagation_map: dict[str, float],
    config: DiffusionConfig,
) -> None:
    """Batch-write propagated_heat, effective_heat, and materialization_level.

    Combines the propagation map produced by :func:`propagate_heat_bfs` with the
    node's existing heat_score to derive effective_heat and the appropriate
    materialization tier.

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.
        propagation_map: Mapping from node ID to its propagated heat value.
        config: Diffusion configuration providing materialization thresholds.
    """
    if not propagation_map:
        return

    now = datetime.datetime.now(datetime.UTC).isoformat()
    updates = [
        {"node_id": node_id, "propagated_heat": heat}
        for node_id, heat in propagation_map.items()
    ]
    log = logger.bind(silo_id=silo_id, update_count=len(updates))
    await store.execute_write(
        UPDATE_PROPAGATED_HEAT_QUERY,
        {
            "silo_id": silo_id,
            "updates": updates,
            "full_threshold": config.thresholds.full,
            "warm_threshold": config.thresholds.warm,
            "structure_threshold": config.thresholds.structure,
            "now": now,
        },
    )
    log.debug("batch_update_propagated_heat.done")


async def get_materialization_distribution(
    store: HyperGraphStore,
    silo_id: str,
) -> dict[str, int]:
    """Return a count of nodes per materialization level for the given silo.

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.

    Returns:
        Mapping from materialization level string to node count.
        Levels not present in the graph are omitted from the result.
    """
    rows = await store.execute_query(
        COUNT_MATERIALIZATION_LEVELS_QUERY,
        {"silo_id": silo_id},
    )
    distribution = {row["level"]: row["count"] for row in rows}
    logger.debug(
        "get_materialization_distribution.done",
        silo_id=silo_id,
        distribution=distribution,
    )
    return distribution


async def diffuse_heat(
    store: HyperGraphStore,
    silo_id: str,
    config: DiffusionConfig,
) -> DiffusionResult:
    """Propagate heat from hot nodes to their graph neighbors.

    Orchestrates the full diffusion pipeline:

    1. Decay existing propagated heat by ``config.propagated_heat_decay``.
    2. Fetch nodes whose ``heat_score`` meets ``config.hot_threshold``.
    3. Fetch the subgraph within ``config.max_depth`` hops of those nodes.
    4. Build the adjacency list and run BFS to compute a propagation map.
    5. Batch-write the resulting propagated heat back to the store.

    Args:
        store: HyperGraphStore protocol implementation.
        silo_id: Tenant silo identifier.
        config: Diffusion configuration parameters.

    Returns:
        :class:`DiffusionResult` summarising the completed run.
    """
    log = logger.bind(silo_id=silo_id)
    log.info("diffuse_heat.start")

    await decay_propagated_heat(store, silo_id, config.propagated_heat_decay)

    hot_nodes = await fetch_hot_nodes(
        store, silo_id, config.hot_threshold, config.max_hot_nodes
    )
    if not hot_nodes:
        log.info("diffuse_heat.no_hot_nodes")
        return DiffusionResult(hot_nodes=0, nodes_updated=0, edge_traversals={})

    hot_node_ids = [n.id for n in hot_nodes]
    edges = await fetch_subgraph(store, silo_id, hot_node_ids, config.max_depth)

    adjacency = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adjacency, config)

    await batch_update_propagated_heat(store, silo_id, result.propagation_map, config)

    log.info(
        "diffuse_heat.done",
        hot_nodes=result.hot_nodes,
        nodes_updated=result.nodes_updated,
        edge_traversals=result.edge_traversals,
    )
    return result


__all__ = [
    "DECAY_PROPAGATED_HEAT_QUERY",
    "COUNT_MATERIALIZATION_LEVELS_QUERY",
    "FETCH_HOT_NODES_QUERY",
    "FETCH_SUBGRAPH_QUERY",
    "UPDATE_PROPAGATED_HEAT_QUERY",
    "DiffusionResult",
    "HotNode",
    "SubgraphEdge",
    "batch_update_propagated_heat",
    "build_adjacency_list",
    "decay_propagated_heat",
    "diffuse_heat",
    "fetch_hot_nodes",
    "fetch_subgraph",
    "get_materialization_distribution",
    "propagate_heat_bfs",
]
