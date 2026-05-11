#!/usr/bin/env python3
"""Benchmark clustering algorithms: Leiden vs Louvain vs LPA.

Usage:
    uv run python scripts/clustering_benchmark.py --silo-id <uuid>

Requires a running Memgraph instance with MAGE loaded.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from dataclasses import dataclass

from context_service.stores.memgraph import MemgraphClient, create_memgraph_driver


@dataclass
class BenchmarkResult:
    algorithm: str
    runs: int
    mean_ms: float
    stddev_ms: float
    community_counts: list[int]
    stability: float  # % of nodes with same community across runs


LEIDEN_QUERY = """
CALL igraphalg.community_leiden("CPM", null, $gamma, 0.01, null, 2, null)
YIELD node, community_id
WITH node, community_id
WHERE node.silo_id = $silo_id
  AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(node))
RETURN node.id AS node_id, community_id
"""

LOUVAIN_QUERY = """
CALL community_detection.louvain()
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


def compute_stability(runs: list[dict[str, int]]) -> float:
    """Compute stability as % of nodes with consistent community assignment."""
    if len(runs) < 2:
        return 1.0

    all_nodes: set[str] = set()
    for run in runs:
        all_nodes.update(run.keys())

    if not all_nodes:
        return 1.0

    stable_count = 0
    for node_id in all_nodes:
        communities = [run.get(node_id) for run in runs if node_id in run]
        if len(set(communities)) == 1:
            stable_count += 1

    return stable_count / len(all_nodes)


async def run_benchmark(
    memgraph: MemgraphClient,
    silo_id: str,
    algorithm: str,
    query: str,
    gamma: float = 1.0,
    num_runs: int = 5,
) -> BenchmarkResult:
    """Run a single algorithm benchmark."""
    timings: list[float] = []
    community_counts: list[int] = []
    assignment_runs: list[dict[str, int]] = []

    params = {"silo_id": silo_id, "gamma": gamma}

    for i in range(num_runs):
        start = time.perf_counter()
        try:
            results = await memgraph.execute_query(query, params)
            elapsed_ms = (time.perf_counter() - start) * 1000
            timings.append(elapsed_ms)

            assignments = {r["node_id"]: r["community_id"] for r in results}
            assignment_runs.append(assignments)
            community_counts.append(len(set(assignments.values())))

            print(
                f"  {algorithm} run {i + 1}: {elapsed_ms:.1f}ms, {community_counts[-1]} communities"
            )
        except Exception as e:
            print(f"  {algorithm} run {i + 1}: FAILED - {e}")
            return BenchmarkResult(
                algorithm=algorithm,
                runs=i,
                mean_ms=0,
                stddev_ms=0,
                community_counts=[],
                stability=0,
            )

    return BenchmarkResult(
        algorithm=algorithm,
        runs=num_runs,
        mean_ms=statistics.mean(timings),
        stddev_ms=statistics.stdev(timings) if len(timings) > 1 else 0,
        community_counts=community_counts,
        stability=compute_stability(assignment_runs),
    )


async def count_nodes(memgraph: MemgraphClient, silo_id: str) -> int:
    """Count eligible nodes for clustering."""
    query = """
    MATCH (n)
    WHERE n.silo_id = $silo_id
      AND any(lbl IN ["Fact", "Claim"] WHERE lbl IN labels(n))
    RETURN count(n) AS cnt
    """
    results = await memgraph.execute_query(query, {"silo_id": silo_id})
    return results[0]["cnt"] if results else 0


async def main(silo_id: str, num_runs: int = 5) -> None:
    driver = await create_memgraph_driver()
    memgraph = MemgraphClient(driver)

    try:
        node_count = await count_nodes(memgraph, silo_id)
        print(f"\nSilo {silo_id}: {node_count} nodes eligible for clustering\n")

        if node_count == 0:
            print("No nodes to cluster. Exiting.")
            return

        algorithms = [
            ("Leiden (γ=0.1)", LEIDEN_QUERY, 0.1),
            ("Leiden (γ=0.01)", LEIDEN_QUERY, 0.01),
            ("Leiden (γ=0.001)", LEIDEN_QUERY, 0.001),
            ("LPA", LPA_QUERY, None),
        ]

        results: list[BenchmarkResult] = []
        for name, query, gamma in algorithms:
            print(f"\nBenchmarking {name}...")
            params_gamma = gamma if gamma else 1.0
            result = await run_benchmark(memgraph, silo_id, name, query, params_gamma, num_runs)
            results.append(result)

        print("\n" + "=" * 70)
        print("RESULTS SUMMARY")
        print("=" * 70)
        print(
            f"{'Algorithm':<25} {'Mean (ms)':<12} {'StdDev':<10} {'Communities':<15} {'Stability':<10}"
        )
        print("-" * 70)

        for r in results:
            if r.runs > 0:
                comm_range = (
                    f"{min(r.community_counts)}-{max(r.community_counts)}"
                    if r.community_counts
                    else "N/A"
                )
                print(
                    f"{r.algorithm:<25} {r.mean_ms:<12.1f} {r.stddev_ms:<10.1f} {comm_range:<15} {r.stability * 100:.1f}%"
                )
            else:
                print(f"{r.algorithm:<25} FAILED")

    finally:
        await driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark clustering algorithms")
    parser.add_argument("--silo-id", required=True, help="Silo UUID to benchmark")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per algorithm")
    args = parser.parse_args()

    asyncio.run(main(args.silo_id, args.runs))
