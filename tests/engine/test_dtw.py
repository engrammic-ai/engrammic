"""Tests for DTW similarity wrapper."""

import pytest

from context_service.engine.dtw import dtw_similarity


def test_dtw_similarity_identical() -> None:
    """Identical sequences have similarity 1.0."""
    steps_a = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    steps_b = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    similarity = dtw_similarity(steps_a, steps_b)
    assert similarity == pytest.approx(1.0, abs=0.01)


def test_dtw_similarity_different() -> None:
    """Different sequences have lower similarity."""
    steps_a = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    steps_b = [[0.9, 0.8, 0.7], [0.6, 0.5, 0.4]]

    similarity = dtw_similarity(steps_a, steps_b)
    assert 0.0 < similarity < 0.5


def test_dtw_similarity_different_lengths() -> None:
    """DTW handles sequences of different lengths."""
    steps_a = [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]]
    steps_b = [[0.1, 0.2], [0.5, 0.6]]

    similarity = dtw_similarity(steps_a, steps_b)
    assert 0.5 < similarity < 1.0


def test_dtw_similarity_empty() -> None:
    """Empty sequences return 0.0 similarity."""
    assert dtw_similarity([], []) == 0.0
    assert dtw_similarity([[0.1, 0.2]], []) == 0.0
    assert dtw_similarity([], [[0.1, 0.2]]) == 0.0
