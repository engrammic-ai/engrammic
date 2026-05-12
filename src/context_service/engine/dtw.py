"""Dynamic Time Warping wrapper for step embedding comparison."""

from __future__ import annotations

import numpy as np
from dtaidistance import dtw_ndim  # type: ignore[import-untyped]


def dtw_similarity(
    steps_a: list[list[float]],
    steps_b: list[list[float]],
) -> float:
    """Compute similarity between two step embedding sequences using DTW.

    Args:
        steps_a: First sequence of step embeddings.
        steps_b: Second sequence of step embeddings.

    Returns:
        Similarity score between 0.0 and 1.0.
    """
    if not steps_a or not steps_b:
        return 0.0

    arr_a = np.array(steps_a, dtype=np.float64)
    arr_b = np.array(steps_b, dtype=np.float64)

    distance: float = float(dtw_ndim.distance(arr_a, arr_b))

    # Convert distance to similarity: 1/(1+d)
    return 1.0 / (1.0 + distance)
