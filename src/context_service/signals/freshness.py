"""Freshness scoring (Gaussian decay with floor).

Pure function: no I/O. Used in retrieval ranking by services/context.py.
"""

from __future__ import annotations

import math
from datetime import datetime

FRESHNESS_FLOOR = 0.25


def compute_freshness(
    created_at: datetime,
    now: datetime,
    sigma_days: int = 30,
) -> float:
    """Gaussian decay freshness score in [FRESHNESS_FLOOR, 1.0].

    Score is ``max(FRESHNESS_FLOOR, exp(-0.5 * (t/sigma)**2))`` where ``t`` is
    age in days. Clock-skewed future timestamps clamp to 1.0.

    Args:
        created_at: When the node was created.
        now: Reference time (caller passes a single ``datetime.now(UTC)`` for
            an entire ranking pass to keep scores consistent).
        sigma_days: Width of the Gaussian. Default 30; older than ~3*sigma
            saturates at the floor.

    Returns:
        Float in [FRESHNESS_FLOOR, 1.0].
    """
    delta = now - created_at
    days = delta.total_seconds() / 86400.0
    if days <= 0:
        return 1.0
    score = math.exp(-0.5 * (days / sigma_days) ** 2)
    return max(FRESHNESS_FLOOR, score)


__all__ = ["FRESHNESS_FLOOR", "compute_freshness"]
