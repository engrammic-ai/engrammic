"""Clustering algorithm benchmark harness.

Run with: uv run pytest tests/benchmarks/test_clustering_algorithms.py -v -s

Requires:
- Running Memgraph with MAGE
- A silo with sufficient edge density (min 100 edges between clusterable nodes)

Skip conditions are checked at collection time.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

import pytest

from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver

LEIDEN_QUERY = """
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(node))
RETURN node.id AS node_id, community_id
"""

LPA_QUERY = """
CALL community_detection.get()
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(node))
RETURN node.id AS node_id, community_id
"""

PRODUCTION_GAMMAS = [0.1, 0.01, 0.001]


@dataclass
class AlgorithmResult:
    name: str
    mean_ms: float
    stddev_ms: float
    community_counts: list[int]
    stability: float


def compute_stability(runs: list[dict[str, int]]) -> float:
    """Compute stability as fraction of nodes with consistent assignment across runs."""
    if len(runs) < 2:
        return 1.0
    all_nodes = set().union(*runs)
    if not all_nodes:
        return 1.0
    stable = sum(1 for n in all_nodes if len({r.get(n) for r in runs if n in r}) == 1)
    return stable / len(all_nodes)


@pytest.fixture(scope="module")
async def memgraph() -> MemgraphClient:
    driver = await create_memgraph_driver()
    client = MemgraphClient(driver)
    yield client
    await driver.close()


@pytest.fixture(scope="module")
async def benchmark_silo(memgraph: MemgraphClient) -> str | None:
    """Find a silo with sufficient edge density for benchmarking."""
    results = await memgraph.execute_query(
        """
        MATCH (a)-[r]-(b)
        WHERE a.silo_id IS NOT NULL
          AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(a))
          AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(b))
        WITH a.silo_id AS silo, count(r) AS edges
        WHERE edges >= 100
        RETURN silo, edges
        ORDER BY edges DESC
        LIMIT 1
        """,
        {},
    )
    if results:
        return str(results[0]["silo"])
    return None


@pytest.fixture(scope="module")
async def silo_stats(memgraph: MemgraphClient, benchmark_silo: str | None) -> dict[str, Any]:
    """Get node and edge counts for the benchmark silo."""
    if not benchmark_silo:
        return {}

    nodes = await memgraph.execute_query(
        """
        MATCH (n)
        WHERE n.silo_id = $silo_id
          AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(n))
        RETURN count(n) AS cnt
        """,
        {"silo_id": benchmark_silo},
    )

    edges = await memgraph.execute_query(
        """
        MATCH (a)-[r]-(b)
        WHERE a.silo_id = $silo_id
          AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(a))
          AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(b))
        RETURN count(r) AS cnt
        """,
        {"silo_id": benchmark_silo},
    )

    return {
        "silo_id": benchmark_silo,
        "nodes": nodes[0]["cnt"] if nodes else 0,
        "edges": edges[0]["cnt"] if edges else 0,
    }


async def run_algorithm(
    memgraph: MemgraphClient,
    silo_id: str,
    query: str,
    gamma: float,
    runs: int = 5,
) -> AlgorithmResult:
    """Run an algorithm multiple times and collect metrics."""
    import time

    timings: list[float] = []
    community_counts: list[int] = []
    assignments: list[dict[str, int]] = []

    for _ in range(runs):
        start = time.perf_counter()
        results = await memgraph.execute_query(query, {"silo_id": silo_id, "gamma": gamma})
        elapsed = (time.perf_counter() - start) * 1000
        timings.append(elapsed)

        assign = {r["node_id"]: r["community_id"] for r in results}
        assignments.append(assign)
        community_counts.append(len(set(assign.values())))

    return AlgorithmResult(
        name=f"query@γ={gamma}",
        mean_ms=statistics.mean(timings),
        stddev_ms=statistics.stdev(timings) if len(timings) > 1 else 0,
        community_counts=community_counts,
        stability=compute_stability(assignments),
    )


@pytest.mark.integration
@pytest.mark.benchmark
class TestClusteringAlgorithms:
    """Benchmark tests for clustering algorithm evaluation."""

    @pytest.fixture(autouse=True)
    def skip_if_no_data(self, benchmark_silo: str | None, silo_stats: dict[str, Any]) -> None:
        if not benchmark_silo:
            pytest.skip("No silo with sufficient edge density (need >= 100 edges)")
        if silo_stats.get("nodes", 0) < 50:
            pytest.skip(f"Silo has too few nodes: {silo_stats.get('nodes', 0)}")

    async def test_leiden_stability(
        self, memgraph: MemgraphClient, benchmark_silo: str, silo_stats: dict[str, Any]
    ) -> None:
        """Leiden should produce stable community assignments across runs."""
        print(
            f"\nSilo: {benchmark_silo} ({silo_stats['nodes']} nodes, {silo_stats['edges']} edges)"
        )

        for gamma in PRODUCTION_GAMMAS:
            result = await run_algorithm(memgraph, benchmark_silo, LEIDEN_QUERY, gamma, runs=5)
            print(f"Leiden γ={gamma}: {result.mean_ms:.1f}ms, {result.stability * 100:.0f}% stable")
            assert result.stability >= 0.95, f"Leiden unstable at γ={gamma}: {result.stability}"

    async def test_lpa_stability(
        self, memgraph: MemgraphClient, benchmark_silo: str, silo_stats: dict[str, Any]
    ) -> None:
        """LPA should produce reasonably stable assignments (known to be non-deterministic)."""
        print(
            f"\nSilo: {benchmark_silo} ({silo_stats['nodes']} nodes, {silo_stats['edges']} edges)"
        )

        result = await run_algorithm(memgraph, benchmark_silo, LPA_QUERY, gamma=1.0, runs=10)
        print(f"LPA: {result.mean_ms:.1f}ms, {result.stability * 100:.0f}% stable")
        # LPA is non-deterministic, accept 80% stability
        assert result.stability >= 0.80, f"LPA too unstable: {result.stability}"

    async def test_lpa_faster_than_leiden(
        self, memgraph: MemgraphClient, benchmark_silo: str
    ) -> None:
        """LPA should be significantly faster than Leiden."""
        leiden = await run_algorithm(memgraph, benchmark_silo, LEIDEN_QUERY, gamma=0.01, runs=5)
        lpa = await run_algorithm(memgraph, benchmark_silo, LPA_QUERY, gamma=1.0, runs=5)

        print(f"\nLeiden: {leiden.mean_ms:.1f}ms, LPA: {lpa.mean_ms:.1f}ms")
        print(f"Speedup: {leiden.mean_ms / lpa.mean_ms:.1f}x")

        assert lpa.mean_ms < leiden.mean_ms, "Expected LPA to be faster than Leiden"

    async def test_community_count_sanity(
        self, memgraph: MemgraphClient, benchmark_silo: str, silo_stats: dict[str, Any]
    ) -> None:
        """Algorithms should find meaningful communities, not 1-per-node."""
        node_count = silo_stats["nodes"]
        max_acceptable = node_count * 0.8  # At most 80% of nodes as separate communities

        leiden = await run_algorithm(memgraph, benchmark_silo, LEIDEN_QUERY, gamma=0.001, runs=3)
        lpa = await run_algorithm(memgraph, benchmark_silo, LPA_QUERY, gamma=1.0, runs=3)

        leiden_avg = statistics.mean(leiden.community_counts)
        lpa_avg = statistics.mean(lpa.community_counts)

        print(f"\nNode count: {node_count}")
        print(f"Leiden communities: {leiden_avg:.0f}")
        print(f"LPA communities: {lpa_avg:.0f}")

        assert leiden_avg < max_acceptable, f"Leiden found too many communities: {leiden_avg}"
        assert lpa_avg < max_acceptable, f"LPA found too many communities: {lpa_avg}"
