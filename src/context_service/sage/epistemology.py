"""Epistemology module: confidence propagation, PPR scoring, corroboration weighting.

Implements CITE v2 epistemology per context/specs/cite-v2-epistemology.md.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

PPR_CACHE_TTL_SECONDS = 300  # 5 minutes


@dataclass
class PPRCacheEntry:
    """Single PPR cache entry with timestamp."""

    scores: dict[str, float]
    created_at: float


class PPRCache:
    """In-memory PPR cache with TTL.

    Keyed by (silo_id, frozenset(query_node_ids)).
    Thread-safe for read/write via dict operations.
    """

    def __init__(self, ttl_seconds: float = PPR_CACHE_TTL_SECONDS) -> None:
        self._cache: dict[tuple[str, frozenset[str]], PPRCacheEntry] = {}
        self._ttl = ttl_seconds

    def get(self, silo_id: str, query_node_ids: list[str]) -> dict[str, float] | None:
        """Get cached PPR scores if valid, None if expired or missing."""
        key = (silo_id, frozenset(query_node_ids))
        entry = self._cache.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > self._ttl:
            del self._cache[key]
            return None
        return entry.scores

    def set(self, silo_id: str, query_node_ids: list[str], scores: dict[str, float]) -> None:
        """Cache PPR scores."""
        key = (silo_id, frozenset(query_node_ids))
        self._cache[key] = PPRCacheEntry(scores=scores, created_at=time.monotonic())

    def invalidate(self, silo_id: str) -> int:
        """Invalidate all cached entries for a silo. Returns count invalidated."""
        to_remove = [k for k in self._cache if k[0] == silo_id]
        for k in to_remove:
            del self._cache[k]
        return len(to_remove)

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()


ppr_cache = PPRCache()


@dataclass
class PropagationResult:
    """Result of confidence propagation."""

    node_ids: list[str]
    confidence_scores: np.ndarray
    iterations: int
    converged: bool

    def as_dict(self) -> dict[str, float]:
        """Return node_id -> confidence mapping."""
        return dict(zip(self.node_ids, self.confidence_scores.tolist(), strict=True))


def build_adjacency_matrices(
    node_ids: Sequence[str],
    support_edges: Sequence[tuple[str, str, float]],
    contradiction_edges: Sequence[tuple[str, str, float]],
) -> tuple[np.ndarray, np.ndarray]:
    """Build row-normalized adjacency matrices for support and contradiction edges.

    Args:
        node_ids: List of node IDs (defines matrix index mapping).
        support_edges: List of (source_id, target_id, weight) tuples.
        contradiction_edges: List of (source_id, target_id, weight) tuples.

    Returns:
        Tuple of (support_matrix, contradiction_matrix), both row-normalized.
    """
    n = len(node_ids)
    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    support_matrix = np.zeros((n, n), dtype=np.float64)
    contradiction_matrix = np.zeros((n, n), dtype=np.float64)

    for source, target, weight in support_edges:
        if source in id_to_idx and target in id_to_idx:
            support_matrix[id_to_idx[target], id_to_idx[source]] = weight

    for source, target, weight in contradiction_edges:
        if source in id_to_idx and target in id_to_idx:
            contradiction_matrix[id_to_idx[target], id_to_idx[source]] = weight

    support_matrix = _row_normalize(support_matrix)
    contradiction_matrix = _row_normalize(contradiction_matrix)

    return support_matrix, contradiction_matrix


def _row_normalize(matrix: np.ndarray) -> np.ndarray:
    """Row-normalize a matrix (rows sum to 1, or 0 if all zeros)."""
    row_sums = matrix.sum(axis=1, keepdims=True)
    row_sums = np.where(row_sums == 0, 1.0, row_sums)
    return matrix / row_sums


def propagate_confidence(
    credibility_scores: np.ndarray,
    support_matrix: np.ndarray,
    contradiction_matrix: np.ndarray,
    alpha: float = 0.8,
    eta: float = 1.0,
    max_iter: int = 100,
    epsilon: float = 1e-6,
) -> tuple[np.ndarray, int, bool]:
    """Propagate confidence through the graph using damped iteration.

    Formula: x_new = clip((1 - alpha) * prior + alpha * (A+ - eta * A-) @ x, 0, 1)

    For nodes with no incoming edges (isolated), confidence equals credibility.

    Args:
        credibility_scores: Prior credibility scores for each node.
        support_matrix: Row-normalized support adjacency matrix.
        contradiction_matrix: Row-normalized contradiction adjacency matrix.
        alpha: Mixing weight for graph structure vs prior (default 0.8).
        eta: Contradiction penalty weight (default 1.0).
        max_iter: Maximum iterations (default 100).
        epsilon: Convergence threshold (default 1e-6).

    Returns:
        Tuple of (confidence_scores, iterations, converged).
    """
    prior = credibility_scores.copy()
    x = prior.copy()

    m = support_matrix - eta * contradiction_matrix

    has_incoming = (support_matrix.sum(axis=1) + contradiction_matrix.sum(axis=1)) > 0

    for iteration in range(max_iter):
        propagated = np.clip((1 - alpha) * prior + alpha * (m @ x), 0, 1)
        x_new = np.where(has_incoming, propagated, prior)

        if np.max(np.abs(x_new - x)) < epsilon:
            return x_new, iteration + 1, True
        x = x_new

    return x, max_iter, False


def propagate_incremental(
    target_id: str,
    node_ids: Sequence[str],
    credibility_scores: dict[str, float],
    support_edges: Sequence[tuple[str, str, float]],
    contradiction_edges: Sequence[tuple[str, str, float]],
    depth: int = 2,
    alpha: float = 0.8,
    eta: float = 1.0,
) -> dict[str, float]:
    """Incremental propagation for write-time (depth-limited, single target).

    Computes confidence update for a single node and its immediate neighborhood.
    Cheaper than full propagation, suitable for < 50ms write-time budget.

    Args:
        target_id: Node to compute confidence for.
        node_ids: All relevant node IDs.
        credibility_scores: Node ID -> credibility mapping.
        support_edges: Support edges (source, target, weight).
        contradiction_edges: Contradiction edges.
        depth: Neighborhood depth to consider (default 2).
        alpha: Mixing weight.
        eta: Contradiction penalty.

    Returns:
        Dict of node_id -> updated confidence for affected nodes.
    """
    neighbors = _get_neighborhood(target_id, support_edges, contradiction_edges, depth)
    neighbors.add(target_id)

    relevant_ids = [nid for nid in node_ids if nid in neighbors]
    if not relevant_ids:
        return {target_id: credibility_scores.get(target_id, 0.5)}

    relevant_support = [(s, t, w) for s, t, w in support_edges if s in neighbors and t in neighbors]
    relevant_contra = [
        (s, t, w) for s, t, w in contradiction_edges if s in neighbors and t in neighbors
    ]

    support_matrix, contra_matrix = build_adjacency_matrices(
        relevant_ids, relevant_support, relevant_contra
    )

    cred_array = np.array([credibility_scores.get(nid, 0.5) for nid in relevant_ids])

    conf, _, _ = propagate_confidence(
        cred_array, support_matrix, contra_matrix, alpha=alpha, eta=eta, max_iter=20
    )

    return dict(zip(relevant_ids, conf.tolist(), strict=True))


def _get_neighborhood(
    node_id: str,
    support_edges: Sequence[tuple[str, str, float]],
    contradiction_edges: Sequence[tuple[str, str, float]],
    depth: int,
) -> set[str]:
    """Get nodes within depth hops of node_id."""
    neighbors: set[str] = set()
    frontier = {node_id}

    for _ in range(depth):
        next_frontier: set[str] = set()
        for nid in frontier:
            for s, t, _ in support_edges:
                if s == nid:
                    next_frontier.add(t)
                elif t == nid:
                    next_frontier.add(s)
            for s, t, _ in contradiction_edges:
                if s == nid:
                    next_frontier.add(t)
                elif t == nid:
                    next_frontier.add(s)
        neighbors.update(frontier)
        frontier = next_frontier - neighbors

    neighbors.update(frontier)
    return neighbors


def compute_corroboration_weight(
    source_claims: dict[str, list[str]],
) -> float:
    """Compute independence-weighted corroboration score.

    Formula from spec Section 2.4:
        source_weight = 1.0 + 0.5 * (sqrt(len(claims_from_source)) - 1)
        total = sum(source_weights)
        normalized = 1 - exp(-0.5 * total)

    Args:
        source_claims: Mapping of source_root -> list of claim IDs from that source.

    Returns:
        Normalized corroboration weight in [0, 1).
    """
    if not source_claims:
        return 0.0

    total_weight = 0.0
    for claims in source_claims.values():
        n_claims = len(claims)
        if n_claims > 0:
            source_weight = 1.0 + 0.5 * (math.sqrt(n_claims) - 1)
            total_weight += source_weight

    return 1.0 - math.exp(-0.5 * total_weight)


def personalized_pagerank(
    node_ids: Sequence[str],
    adjacency: np.ndarray,
    query_node_ids: Sequence[str],
    alpha: float = 0.85,
    max_iter: int = 100,
    epsilon: float = 1e-6,
) -> dict[str, float]:
    """Compute Personalized PageRank scores from query nodes.

    Args:
        node_ids: All node IDs (defines index mapping).
        adjacency: Combined adjacency matrix (support - contradiction).
        query_node_ids: Seed nodes for PPR (typically top-5 recall anchors).
        alpha: Teleport probability (default 0.85).
        max_iter: Maximum iterations.
        epsilon: Convergence threshold.

    Returns:
        Dict of node_id -> PPR score.
    """
    n = len(node_ids)
    if n == 0:
        return {}

    id_to_idx = {nid: i for i, nid in enumerate(node_ids)}

    teleport = np.zeros(n)
    seed_count = 0
    for qid in query_node_ids:
        if qid in id_to_idx:
            teleport[id_to_idx[qid]] = 1.0
            seed_count += 1

    if seed_count == 0:
        teleport[:] = 1.0 / n
    else:
        teleport /= seed_count

    adj_normalized = _column_normalize(adjacency)

    scores = teleport.copy()
    for _ in range(max_iter):
        scores_new = (1 - alpha) * teleport + alpha * (adj_normalized @ scores)
        if np.max(np.abs(scores_new - scores)) < epsilon:
            break
        scores = scores_new

    return dict(zip(node_ids, scores.tolist(), strict=True))


def _column_normalize(matrix: np.ndarray) -> np.ndarray:
    """Column-normalize a matrix (columns sum to 1, or uniform if all zeros)."""
    col_sums = matrix.sum(axis=0, keepdims=True)
    col_sums = np.where(col_sums == 0, 1.0, col_sums)
    return matrix / col_sums
