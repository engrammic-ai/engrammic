"""Tests for epistemology module: propagation, PPR, corroboration."""

from __future__ import annotations

import math

import numpy as np
import pytest

from context_service.sage.epistemology import (
    build_adjacency_matrices,
    compute_corroboration_weight,
    personalized_pagerank,
    propagate_confidence,
    propagate_incremental,
)


class TestBuildAdjacencyMatrices:
    """Tests for build_adjacency_matrices."""

    def test_empty_graph(self) -> None:
        node_ids = ["a", "b", "c"]
        support, contra = build_adjacency_matrices(node_ids, [], [])

        assert support.shape == (3, 3)
        assert contra.shape == (3, 3)
        np.testing.assert_array_equal(support, np.zeros((3, 3)))
        np.testing.assert_array_equal(contra, np.zeros((3, 3)))

    def test_support_edge_placement(self) -> None:
        node_ids = ["a", "b"]
        support_edges = [("a", "b", 1.0)]

        support, _ = build_adjacency_matrices(node_ids, support_edges, [])

        assert support[1, 0] == 1.0
        assert support[0, 1] == 0.0

    def test_row_normalization(self) -> None:
        node_ids = ["a", "b", "c"]
        support_edges = [("a", "b", 2.0), ("a", "c", 2.0)]

        support, _ = build_adjacency_matrices(node_ids, support_edges, [])

        row_sums = support.sum(axis=1)
        for row_sum in row_sums:
            assert row_sum == pytest.approx(0.0) or row_sum == pytest.approx(1.0)


class TestPropagateConfidence:
    """Tests for propagate_confidence."""

    def test_no_edges_preserves_credibility(self) -> None:
        credibility = np.array([0.8, 0.6, 0.4])
        support = np.zeros((3, 3))
        contra = np.zeros((3, 3))

        conf, _, converged = propagate_confidence(credibility, support, contra)

        np.testing.assert_array_almost_equal(conf, credibility)
        assert converged

    def test_support_increases_confidence(self) -> None:
        node_ids = ["high", "low"]
        support_edges = [("high", "low", 1.0)]
        support, contra = build_adjacency_matrices(node_ids, support_edges, [])

        credibility = np.array([0.9, 0.3])
        conf, _, _ = propagate_confidence(credibility, support, contra, alpha=0.5)

        assert conf[1] > 0.3

    def test_contradiction_decreases_confidence(self) -> None:
        node_ids = ["a", "b"]
        contra_edges = [("a", "b", 1.0)]
        support, contra = build_adjacency_matrices(node_ids, [], contra_edges)

        credibility = np.array([0.9, 0.7])
        conf, _, _ = propagate_confidence(credibility, support, contra, alpha=0.5, eta=1.0)

        assert conf[1] < 0.7

    def test_convergence(self) -> None:
        credibility = np.array([0.5, 0.5, 0.5])
        support = np.eye(3) * 0.1
        contra = np.zeros((3, 3))

        _, iters, converged = propagate_confidence(
            credibility, support, contra, max_iter=100, epsilon=1e-6
        )

        assert converged
        assert iters < 100

    def test_clipping_bounds(self) -> None:
        credibility = np.array([1.0, 0.0])
        support = np.array([[0, 1], [1, 0]], dtype=float)
        contra = np.array([[0, 0.5], [0.5, 0]], dtype=float)

        conf, _, _ = propagate_confidence(
            credibility, support, contra, alpha=0.99, eta=2.0, max_iter=50
        )

        assert np.all(conf >= 0)
        assert np.all(conf <= 1)


class TestPropagateIncremental:
    """Tests for propagate_incremental (write-time, depth-limited)."""

    def test_single_node_no_edges(self) -> None:
        result = propagate_incremental(
            target_id="a",
            node_ids=["a", "b", "c"],
            credibility_scores={"a": 0.7, "b": 0.5, "c": 0.3},
            support_edges=[],
            contradiction_edges=[],
            depth=2,
        )

        assert "a" in result
        assert result["a"] == pytest.approx(0.7)

    def test_depth_limited(self) -> None:
        result = propagate_incremental(
            target_id="a",
            node_ids=["a", "b", "c", "d"],
            credibility_scores={"a": 0.5, "b": 0.8, "c": 0.8, "d": 0.8},
            support_edges=[("b", "a", 1.0), ("c", "b", 1.0), ("d", "c", 1.0)],
            contradiction_edges=[],
            depth=1,
        )

        assert "a" in result
        assert "b" in result
        assert "d" not in result


class TestComputeCorroborationWeight:
    """Tests for compute_corroboration_weight."""

    def test_empty_returns_zero(self) -> None:
        assert compute_corroboration_weight({}) == 0.0

    def test_single_source_single_claim(self) -> None:
        weight = compute_corroboration_weight({"source1": ["claim1"]})
        expected = 1.0 - math.exp(-0.5 * 1.0)
        assert weight == pytest.approx(expected)

    def test_multiple_sources_more_weight(self) -> None:
        single = compute_corroboration_weight({"s1": ["c1"]})
        double = compute_corroboration_weight({"s1": ["c1"], "s2": ["c2"]})

        assert double > single

    def test_same_source_diminishing_returns(self) -> None:
        two_sources = compute_corroboration_weight({"s1": ["c1"], "s2": ["c2"]})
        one_source_two_claims = compute_corroboration_weight({"s1": ["c1", "c2"]})

        assert two_sources > one_source_two_claims

    def test_bounded_zero_one(self) -> None:
        many = compute_corroboration_weight({f"s{i}": [f"c{i}"] for i in range(100)})

        assert 0 <= many <= 1


class TestPersonalizedPagerank:
    """Tests for personalized_pagerank."""

    def test_empty_graph(self) -> None:
        result = personalized_pagerank([], np.array([[]]), [])
        assert result == {}

    def test_query_nodes_get_high_score(self) -> None:
        node_ids = ["a", "b", "c"]
        adj = np.array([[0, 0.5, 0], [0.5, 0, 0.5], [0, 0.5, 0]])

        result = personalized_pagerank(node_ids, adj, ["a"], alpha=0.85)

        assert result["a"] > result["c"]

    def test_connected_nodes_score_higher(self) -> None:
        node_ids = ["a", "b", "isolated"]
        adj = np.array([[0, 1, 0], [1, 0, 0], [0, 0, 0]])

        result = personalized_pagerank(node_ids, adj, ["a"])

        assert result["b"] > result["isolated"]

    def test_scores_sum_approximately_one(self) -> None:
        node_ids = ["a", "b", "c"]
        adj = np.array([[0, 0.5, 0.5], [0.5, 0, 0.5], [0.5, 0.5, 0]])

        result = personalized_pagerank(node_ids, adj, ["a"])

        assert sum(result.values()) == pytest.approx(1.0, abs=0.01)


class TestPPRCache:
    """Tests for PPRCache with TTL."""

    def test_set_and_get(self) -> None:
        from context_service.sage.epistemology import PPRCache

        cache = PPRCache(ttl_seconds=300)
        scores = {"a": 0.5, "b": 0.3, "c": 0.2}

        cache.set("silo1", ["anchor1", "anchor2"], scores)
        result = cache.get("silo1", ["anchor1", "anchor2"])

        assert result == scores

    def test_returns_none_for_missing(self) -> None:
        from context_service.sage.epistemology import PPRCache

        cache = PPRCache(ttl_seconds=300)

        result = cache.get("silo1", ["unknown"])

        assert result is None

    def test_key_is_order_independent(self) -> None:
        from context_service.sage.epistemology import PPRCache

        cache = PPRCache(ttl_seconds=300)
        scores = {"a": 0.5, "b": 0.5}

        cache.set("silo1", ["b", "a"], scores)
        result = cache.get("silo1", ["a", "b"])

        assert result == scores

    def test_invalidate_silo(self) -> None:
        from context_service.sage.epistemology import PPRCache

        cache = PPRCache(ttl_seconds=300)
        cache.set("silo1", ["a"], {"x": 1.0})
        cache.set("silo2", ["b"], {"y": 1.0})

        count = cache.invalidate("silo1")

        assert count == 1
        assert cache.get("silo1", ["a"]) is None
        assert cache.get("silo2", ["b"]) == {"y": 1.0}

    def test_expired_entry_returns_none(self) -> None:
        from context_service.sage.epistemology import PPRCache

        cache = PPRCache(ttl_seconds=0.001)
        cache.set("silo1", ["a"], {"x": 1.0})

        import time

        time.sleep(0.01)

        result = cache.get("silo1", ["a"])

        assert result is None
