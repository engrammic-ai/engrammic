"""Integration tests for heat diffusion pipeline."""

import pytest

from context_service.config.diffusion import DiffusionConfig
from context_service.signals.diffusion import (
    HotNode,
    SubgraphEdge,
    build_adjacency_list,
    propagate_heat_bfs,
)


class TestHeatDiffusionIntegration:
    """Test heat diffusion with realistic graph structures."""

    def test_linear_chain_propagation(self):
        """Heat decays along a linear chain: A -> B -> C -> D"""
        config = DiffusionConfig(hop_decay=0.7, max_depth=3)

        edges = [
            SubgraphEdge("A", "B", "SUPPORTS", 1.0),
            SubgraphEdge("B", "C", "SUPPORTS", 1.0),
            SubgraphEdge("C", "D", "SUPPORTS", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="A", heat_score=1.0)]

        result = propagate_heat_bfs(hot_nodes, adjacency, config)

        assert result.propagation_map["B"] > result.propagation_map["C"]
        assert result.propagation_map["C"] > result.propagation_map["D"]

    def test_multiple_sources_max_heat(self):
        """Node reached by multiple hot sources gets max heat."""
        config = DiffusionConfig(hop_decay=0.7, max_depth=2)

        edges = [
            SubgraphEdge("hot1", "target", "SUPPORTS", 1.0),
            SubgraphEdge("hot2", "target", "SUPPORTS", 1.0),
        ]
        adjacency = build_adjacency_list(edges)

        hot_nodes = [
            HotNode(id="hot1", heat_score=1.0),
            HotNode(id="hot2", heat_score=0.5),
        ]

        result = propagate_heat_bfs(hot_nodes, adjacency, config)

        # hot1 contributes 1.0 * 0.7 * 0.9 * 1.0 = 0.63 (the max)
        expected_from_hot1 = 1.0 * 0.7 * 0.9 * 1.0
        assert result.propagation_map["target"] == pytest.approx(expected_from_hot1, rel=0.01)

    def test_edge_type_weights(self):
        """Different edge types propagate different amounts of heat."""
        config = DiffusionConfig(hop_decay=1.0, max_depth=1)

        edges = [
            SubgraphEdge("hot", "contradicts_target", "CONTRADICTS", 1.0),
            SubgraphEdge("hot", "related_target", "RELATED_TO", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="hot", heat_score=1.0)]

        result = propagate_heat_bfs(hot_nodes, adjacency, config)

        assert result.propagation_map["contradicts_target"] == pytest.approx(0.95, rel=0.01)
        assert result.propagation_map["related_target"] == pytest.approx(0.40, rel=0.01)

    def test_edge_heat_affects_propagation(self):
        """Edges with low heat propagate less."""
        config = DiffusionConfig(hop_decay=1.0, max_depth=1)

        edges = [
            SubgraphEdge("hot", "hot_edge", "SUPPORTS", 1.0),
            SubgraphEdge("hot", "cold_edge", "SUPPORTS", 0.1),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="hot", heat_score=1.0)]

        result = propagate_heat_bfs(hot_nodes, adjacency, config)

        assert result.propagation_map["hot_edge"] > result.propagation_map["cold_edge"] * 5

    def test_min_threshold_stops_propagation(self):
        """Propagation stops when heat falls below threshold.

        With hop_decay=0.1 and SUPPORTS weight=0.90:
          A->B: 1.0 * 0.1 * 0.90 * 1.0 = 0.09  (above min_threshold=0.05, B is reached)
          B->C: 0.09 * 0.1 * 0.90 * 1.0 = 0.0081 (below threshold, C is pruned)
        """
        config = DiffusionConfig(hop_decay=0.1, min_threshold=0.05, max_depth=5)

        edges = [
            SubgraphEdge("A", "B", "SUPPORTS", 1.0),
            SubgraphEdge("B", "C", "SUPPORTS", 1.0),
            SubgraphEdge("C", "D", "SUPPORTS", 1.0),
        ]
        adjacency = build_adjacency_list(edges)
        hot_nodes = [HotNode(id="A", heat_score=1.0)]

        result = propagate_heat_bfs(hot_nodes, adjacency, config)

        assert "B" in result.propagation_map
        assert "D" not in result.propagation_map
