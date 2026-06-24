"""Personalized PageRank (PPR) channel for TEMPR retrieval.

Pure Python implementation with no Memgraph MAGE dependency.
Operates on an in-memory adjacency representation built from
HyperGraph edges fetched by the caller.

Algorithm:
    Iterative power iteration with teleportation to seed nodes.
    r(t+1) = d * A * r(t) + (1-d) * seed_vector
    where d is the damping factor and A is the column-stochastic
    transition matrix.
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)


class PersonalizedPageRank:
    """Iterative PPR over an in-memory weighted graph.

    Parameters
    ----------
    damping:
        Probability of following an edge rather than teleporting back to a
        seed node.  Standard value is 0.85.
    max_iterations:
        Hard cap on power-iteration steps.
    tolerance:
        L1 norm convergence threshold.  Iteration stops early when the score
        vector changes by less than this amount.
    """

    def __init__(
        self,
        damping: float = 0.85,
        max_iterations: int = 50,
        tolerance: float = 1e-6,
    ) -> None:
        if not 0.0 < damping < 1.0:
            raise ValueError(f"damping must be in (0, 1), got {damping}")
        if max_iterations < 1:
            raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
        if tolerance < 0.0:
            raise ValueError(f"tolerance must be >= 0, got {tolerance}")

        self.damping = damping
        self.max_iterations = max_iterations
        self.tolerance = tolerance

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        seed_ids: list[str],
        adjacency: dict[str, list[tuple[str, float]]],
        seed_weights: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Run PPR from *seed_ids* over the weighted *adjacency* graph.

        Parameters
        ----------
        seed_ids:
            Node IDs from which teleportation probability is distributed.
            Nodes not present in *adjacency* are silently ignored (they
            contribute 0 outbound weight but still appear in the seed
            distribution if present as keys in adjacency or referenced
            as neighbours).
        adjacency:
            Mapping ``node_id -> [(neighbour_id, edge_weight), ...]``.
            Edge weights must be non-negative; zero-weight edges are
            treated as absent.  Nodes with no outbound edges are treated
            as dangling nodes (their rank mass is redistributed to seeds).
        seed_weights:
            Optional per-seed importance weights. If provided, seeds are
            weighted proportionally (normalized to sum to 1). If None,
            seeds get uniform weight. Use for heat-boosted personalization.

        Returns
        -------
        dict[str, float]
            PPR score for every node encountered in the graph.  Scores
            sum to approximately 1.0.  Returns an empty dict when
            *seed_ids* is empty or no nodes are reachable.
        """
        if not seed_ids:
            return {}

        # Collect all node ids (keys + neighbour references)
        all_nodes: set[str] = set(adjacency.keys())
        for neighbours in adjacency.values():
            for nbr_id, _ in neighbours:
                all_nodes.add(nbr_id)

        if not all_nodes:
            return {}

        # Index nodes for O(1) lookup
        node_list = sorted(all_nodes)
        node_index: dict[str, int] = {n: i for i, n in enumerate(node_list)}
        n = len(node_list)

        # Build column-stochastic transition weights (sparse dict of dicts)
        # transition[j][i] = weight of edge i -> j (contribution to column j)
        # We store as out_weight[i] = sum of outbound weights from i
        out_weight: list[float] = [0.0] * n
        edges: list[list[tuple[int, float]]] = [[] for _ in range(n)]

        for src_id, neighbours in adjacency.items():
            if src_id not in node_index:
                continue
            src = node_index[src_id]
            for nbr_id, weight in neighbours:
                if weight <= 0.0:
                    continue
                if nbr_id not in node_index:
                    continue
                dst = node_index[nbr_id]
                edges[src].append((dst, weight))
                out_weight[src] += weight

        # Seed distribution: weighted or uniform over valid seed nodes
        valid_seed_ids = [s for s in seed_ids if s in node_index]
        if not valid_seed_ids:
            return {}

        seed_vector: list[float] = [0.0] * n
        if seed_weights:
            # Weighted distribution: normalize provided weights
            raw_weights = [seed_weights.get(sid, 1.0) for sid in valid_seed_ids]
            total = sum(raw_weights) or 1.0
            for sid, w in zip(valid_seed_ids, raw_weights, strict=True):
                seed_vector[node_index[sid]] = w / total
        else:
            # Uniform distribution
            seed_prob = 1.0 / len(valid_seed_ids)
            for sid in valid_seed_ids:
                seed_vector[node_index[sid]] = seed_prob
        valid_seeds = [node_index[sid] for sid in valid_seed_ids]

        # Initial rank vector = seed distribution
        rank: list[float] = list(seed_vector)

        teleport_weight = 1.0 - self.damping

        for iteration in range(self.max_iterations):
            new_rank: list[float] = [0.0] * n

            dangling_mass = 0.0

            for i in range(n):
                if out_weight[i] == 0.0:
                    # Dangling node: redistribute mass to seeds
                    dangling_mass += rank[i]
                else:
                    w_total = out_weight[i]
                    for dst, weight in edges[i]:
                        new_rank[dst] += self.damping * rank[i] * (weight / w_total)

            # Distribute dangling mass to seeds proportionally
            for s in valid_seeds:
                new_rank[s] += self.damping * dangling_mass * seed_vector[s]

            # Teleportation
            for i in range(n):
                new_rank[i] += teleport_weight * seed_vector[i]

            # Convergence check (L1 norm)
            delta = sum(abs(new_rank[i] - rank[i]) for i in range(n))
            rank = new_rank

            if delta < self.tolerance:
                logger.debug(
                    "ppr.converged",
                    iterations=iteration + 1,
                    delta=delta,
                )
                break
        else:
            logger.debug(
                "ppr.max_iterations_reached",
                max_iterations=self.max_iterations,
            )

        return {node_list[i]: rank[i] for i in range(n)}
