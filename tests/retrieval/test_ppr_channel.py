"""Tests for the PersonalizedPageRank PPR channel."""

from __future__ import annotations

import pytest

from context_service.retrieval.ppr import PersonalizedPageRank


def _make_ppr(**kwargs: object) -> PersonalizedPageRank:
    return PersonalizedPageRank(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------


def test_ppr_from_seeds() -> None:
    """Seed node A should have the highest PPR score in A->B->C chain."""
    ppr = _make_ppr()
    adjacency = {
        "A": [("B", 1.0)],
        "B": [("C", 1.0)],
        "C": [],
    }
    scores = ppr.compute(["A"], adjacency)

    assert set(scores) == {"A", "B", "C"}
    # Seed A receives teleportation mass on every step so it should rank first
    assert scores["A"] > scores["B"] > scores["C"]


def test_ppr_empty_seeds() -> None:
    """Empty seed list returns an empty scores dict."""
    ppr = _make_ppr()
    adjacency = {"A": [("B", 1.0)], "B": []}
    scores = ppr.compute([], adjacency)
    assert scores == {}


def test_ppr_weighted_edges() -> None:
    """A node reached via a heavier edge should score higher than one reached
    via a lighter edge when both are equidistant from the seed."""
    ppr = _make_ppr()
    # Seed -> heavy_node (weight 10) and Seed -> light_node (weight 1)
    adjacency = {
        "seed": [("heavy_node", 10.0), ("light_node", 1.0)],
        "heavy_node": [],
        "light_node": [],
    }
    scores = ppr.compute(["seed"], adjacency)

    assert scores["heavy_node"] > scores["light_node"]


def test_ppr_respects_max_iterations() -> None:
    """Setting max_iterations=1 should still return a valid (non-empty) result
    and must not run more than one iteration."""
    ppr = _make_ppr(max_iterations=1, tolerance=0.0)
    adjacency = {
        "A": [("B", 1.0)],
        "B": [("A", 1.0)],
    }
    scores = ppr.compute(["A"], adjacency)

    assert set(scores) == {"A", "B"}
    # Scores must be non-negative and sum to approximately 1
    assert all(v >= 0 for v in scores.values())
    total = sum(scores.values())
    assert abs(total - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_ppr_single_node_no_edges() -> None:
    """Single dangling seed node: all mass stays at the seed."""
    ppr = _make_ppr()
    scores = ppr.compute(["A"], {"A": []})
    assert abs(scores["A"] - 1.0) < 1e-6


def test_ppr_seed_not_in_adjacency() -> None:
    """Seed node not present as a key in adjacency is treated as dangling."""
    ppr = _make_ppr()
    # "X" appears only as a neighbour, not as a key
    scores = ppr.compute(["X"], {"A": [("X", 1.0)]})
    # X is a valid seed; should appear in output
    assert "X" in scores
    assert scores["X"] > 0


def test_ppr_multiple_seeds() -> None:
    """Multiple seeds spread teleportation mass; both should receive positive scores."""
    ppr = _make_ppr()
    adjacency = {
        "S1": [("M", 1.0)],
        "S2": [("M", 1.0)],
        "M": [],
    }
    scores = ppr.compute(["S1", "S2"], adjacency)

    # Seeds share teleportation mass equally so they score the same
    assert abs(scores["S1"] - scores["S2"]) < 1e-9
    # Each seed has positive score
    assert scores["S1"] > 0
    assert scores["S2"] > 0
    # M has two inbound edges (from both seeds) so it aggregates more flow
    assert scores["M"] > scores["S1"]


def test_ppr_zero_weight_edges_ignored() -> None:
    """Zero-weight edges must not contribute to propagation."""
    ppr = _make_ppr()
    adjacency = {
        "A": [("B", 0.0), ("C", 1.0)],
        "B": [],
        "C": [],
    }
    scores = ppr.compute(["A"], adjacency)
    # B should receive no propagated mass from A
    assert scores["C"] > scores["B"]


def test_ppr_invalid_damping() -> None:
    with pytest.raises(ValueError, match="damping"):
        PersonalizedPageRank(damping=1.0)

    with pytest.raises(ValueError, match="damping"):
        PersonalizedPageRank(damping=0.0)


def test_ppr_invalid_max_iterations() -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        PersonalizedPageRank(max_iterations=0)


def test_ppr_scores_sum_to_one() -> None:
    """PPR scores should be a probability distribution (sum ~ 1)."""
    ppr = _make_ppr()
    adjacency = {
        "A": [("B", 2.0), ("C", 1.0)],
        "B": [("C", 1.0), ("A", 0.5)],
        "C": [("A", 1.0)],
    }
    scores = ppr.compute(["A"], adjacency)
    total = sum(scores.values())
    assert abs(total - 1.0) < 1e-5
