"""Unit tests for the heat diffusion BFS algorithm and data models."""

from __future__ import annotations

from context_service.config.diffusion import DiffusionConfig
from context_service.signals.diffusion import (
    DiffusionResult,
    HotNode,
    SubgraphEdge,
    build_adjacency_list,
    propagate_heat_bfs,
)


def test_subgraph_edge_model() -> None:
    edge = SubgraphEdge(
        source_id="a",
        target_id="b",
        edge_type="RELATED_TO",
        edge_heat=0.8,
    )
    assert edge.source_id == "a"
    assert edge.target_id == "b"
    assert edge.edge_type == "RELATED_TO"
    assert edge.edge_heat == 0.8


def test_subgraph_edge_model_none_heat() -> None:
    edge = SubgraphEdge(
        source_id="x",
        target_id="y",
        edge_type="SUPPORTS",
        edge_heat=None,
    )
    assert edge.edge_heat is None


def test_hot_node_model() -> None:
    node = HotNode(id="node-1", heat_score=0.75)
    assert node.id == "node-1"
    assert node.heat_score == 0.75


def test_diffusion_result_defaults() -> None:
    result = DiffusionResult(
        hot_nodes=3,
        nodes_updated=5,
        edge_traversals={"RELATED_TO": 2},
    )
    assert result.hot_nodes == 3
    assert result.nodes_updated == 5
    assert result.edge_traversals == {"RELATED_TO": 2}
    assert result.propagation_map == {}


def test_build_adjacency_list_bidirectional() -> None:
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=0.5),
        SubgraphEdge(source_id="b", target_id="c", edge_type="SUPPORTS", edge_heat=0.6),
    ]
    adj = build_adjacency_list(edges)

    # Forward directions
    assert "a" in adj
    assert "b" in adj
    assert "c" in adj

    # a -> b
    assert any(e.target_id == "b" for e in adj["a"])
    # b -> a (reverse)
    assert any(e.target_id == "a" for e in adj["b"])
    # b -> c
    assert any(e.target_id == "c" for e in adj["b"])
    # c -> b (reverse)
    assert any(e.target_id == "b" for e in adj["c"])


def test_build_adjacency_list_empty() -> None:
    adj = build_adjacency_list([])
    assert adj == {}


def test_build_adjacency_list_edge_count() -> None:
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=None),
    ]
    adj = build_adjacency_list(edges)
    # Each undirected edge adds one entry in each direction
    assert len(adj["a"]) == 1
    assert len(adj["b"]) == 1


def test_propagate_heat_bfs_decay() -> None:
    """Verify that heat decays correctly across one hop."""
    config = DiffusionConfig(
        hop_decay=0.7,
        min_threshold=0.01,
        max_depth=3,
        edge_weights={"RELATED_TO": 0.4},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    # propagated = 1.0 * 0.7 (hop_decay) * 0.4 (edge_weight) * 1.0 (edge_heat) = 0.28
    assert "b" in result.propagation_map
    assert abs(result.propagation_map["b"] - 0.28) < 1e-9


def test_propagate_heat_bfs_edge_heat_none_defaults_to_one() -> None:
    """When edge_heat is None it should be treated as 1.0."""
    config = DiffusionConfig(
        hop_decay=0.7,
        min_threshold=0.01,
        max_depth=3,
        edge_weights={"RELATED_TO": 0.4},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=None),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    # edge_heat defaults to 1.0 -> same as above
    assert abs(result.propagation_map["b"] - 0.28) < 1e-9


def test_propagate_heat_bfs_uses_max_for_multiple_sources() -> None:
    """When two hot nodes reach the same neighbour, max() wins."""
    config = DiffusionConfig(
        hop_decay=1.0,
        min_threshold=0.01,
        max_depth=3,
        edge_weights={"RELATED_TO": 1.0},
    )
    hot_nodes = [
        HotNode(id="a", heat_score=0.9),
        HotNode(id="b", heat_score=0.5),
    ]
    edges = [
        SubgraphEdge(source_id="a", target_id="c", edge_type="RELATED_TO", edge_heat=1.0),
        SubgraphEdge(source_id="b", target_id="c", edge_type="RELATED_TO", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    # a propagates 0.9; b propagates 0.5 -> max is 0.9
    assert abs(result.propagation_map["c"] - 0.9) < 1e-9


def test_propagate_heat_bfs_stops_at_min_threshold() -> None:
    """Nodes below min_threshold should not appear in propagation_map."""
    config = DiffusionConfig(
        hop_decay=0.01,  # very aggressive decay
        min_threshold=0.05,
        max_depth=3,
        edge_weights={"RELATED_TO": 0.4},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    # propagated = 1.0 * 0.01 * 0.4 * 1.0 = 0.004 < 0.05 threshold -> pruned
    assert "b" not in result.propagation_map


def test_propagate_heat_bfs_respects_max_depth() -> None:
    """Heat should not propagate beyond max_depth hops."""
    config = DiffusionConfig(
        hop_decay=0.9,
        min_threshold=0.001,
        max_depth=1,
        edge_weights={"RELATED_TO": 1.0},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=1.0),
        SubgraphEdge(source_id="b", target_id="c", edge_type="RELATED_TO", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    assert "b" in result.propagation_map
    assert "c" not in result.propagation_map


def test_propagate_heat_bfs_tracks_edge_traversals() -> None:
    config = DiffusionConfig(
        hop_decay=0.7,
        min_threshold=0.01,
        max_depth=3,
        edge_weights={"RELATED_TO": 0.4, "SUPPORTS": 0.9},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=1.0),
        SubgraphEdge(source_id="a", target_id="c", edge_type="SUPPORTS", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    assert result.edge_traversals.get("RELATED_TO", 0) >= 1
    assert result.edge_traversals.get("SUPPORTS", 0) >= 1


def test_propagate_heat_bfs_nodes_updated_count() -> None:
    config = DiffusionConfig(
        hop_decay=0.7,
        min_threshold=0.01,
        max_depth=3,
        edge_weights={"RELATED_TO": 0.4},
    )
    hot_nodes = [HotNode(id="a", heat_score=1.0)]
    edges = [
        SubgraphEdge(source_id="a", target_id="b", edge_type="RELATED_TO", edge_heat=1.0),
        SubgraphEdge(source_id="a", target_id="c", edge_type="RELATED_TO", edge_heat=1.0),
    ]
    adj = build_adjacency_list(edges)
    result = propagate_heat_bfs(hot_nodes, adj, config)

    assert result.nodes_updated == len(result.propagation_map)


def test_propagate_heat_bfs_no_hot_nodes() -> None:
    config = DiffusionConfig()
    result = propagate_heat_bfs([], {}, config)
    assert result.hot_nodes == 0
    assert result.nodes_updated == 0
    assert result.propagation_map == {}
