"""Test embedding-based belief overlap detection."""

import math
from itertools import combinations

import pytest


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def find_overlapping_pairs(
    beliefs: list[dict],
    threshold: float = 0.85,
    max_pairs: int = 50,
) -> list[tuple[str, str, float]]:
    """Return (belief1_id, belief2_id, similarity) for pairs above threshold."""
    pairs: list[tuple[str, str, float]] = []
    for b1, b2 in combinations(beliefs, 2):
        sim = cosine_similarity(b1["embedding"], b2["embedding"])
        if sim >= threshold:
            pairs.append((b1["belief_id"], b2["belief_id"], sim))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs[:max_pairs]


def test_cosine_similarity_identical_vectors():
    """Identical vectors have similarity 1.0."""
    vec = [0.5, 0.5, 0.5]
    assert cosine_similarity(vec, vec) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    """Orthogonal vectors have similarity 0.0."""
    a = [1.0, 0.0, 0.0]
    b = [0.0, 1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite_vectors():
    """Opposite vectors have similarity -1.0."""
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert cosine_similarity(a, b) == pytest.approx(-1.0)


def test_find_overlapping_pairs_above_threshold():
    """Pairs above threshold are returned."""
    beliefs = [
        {"belief_id": "b1", "embedding": [1.0, 0.0, 0.0]},
        {"belief_id": "b2", "embedding": [0.99, 0.1, 0.0]},
        {"belief_id": "b3", "embedding": [0.0, 1.0, 0.0]},
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.9)

    assert len(pairs) == 1
    assert pairs[0][0] == "b1"
    assert pairs[0][1] == "b2"
    assert pairs[0][2] > 0.9


def test_find_overlapping_pairs_respects_max():
    """Max pairs limit is respected."""
    beliefs = [
        {"belief_id": f"b{i}", "embedding": [1.0, 0.01 * i, 0.0]}
        for i in range(5)
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.9, max_pairs=3)

    assert len(pairs) == 3


def test_find_overlapping_pairs_sorted_by_similarity():
    """Results are sorted by similarity descending."""
    beliefs = [
        {"belief_id": "b1", "embedding": [1.0, 0.0, 0.0]},
        {"belief_id": "b2", "embedding": [0.9, 0.1, 0.0]},
        {"belief_id": "b3", "embedding": [0.95, 0.05, 0.0]},
    ]
    pairs = find_overlapping_pairs(beliefs, threshold=0.8)

    assert pairs[0][2] >= pairs[1][2]
