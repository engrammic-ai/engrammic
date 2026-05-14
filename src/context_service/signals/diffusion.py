"""Heat diffusion BFS algorithm and data models.

Implements a breadth-first heat propagation over a subgraph. Hot nodes seed
the BFS; heat decays at each hop according to DiffusionConfig parameters.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

from context_service.config.diffusion import DiffusionConfig


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


__all__ = [
    "DiffusionResult",
    "HotNode",
    "SubgraphEdge",
    "build_adjacency_list",
    "propagate_heat_bfs",
]
