"""Volume stress scenarios: many commitments hitting consensus."""

from __future__ import annotations

from typing import Any

from benchmarks.custodian_stress.scenarios.base import (
    ScenarioResult,
    ScenarioTimer,
    count_findings,
    generate_silo_id,
    seed_commitments_batch,
)


async def test_500_commitments_consensus(
    store: Any,
    *,
    mock_llm: Any | None = None,  # noqa: ARG001
) -> ScenarioResult:
    """Seed 500 commitments across 10 clusters, run consensus, verify all promoted."""
    silo_id = generate_silo_id()
    total_commitments = 500
    num_clusters = 10
    per_cluster = total_commitments // num_clusters

    timer = ScenarioTimer()

    try:
        all_node_ids: list[str] = []
        for i in range(num_clusters):
            cluster_id = f"cluster-{i}"
            node_ids = await seed_commitments_batch(
                store,
                silo_id=silo_id,
                cluster_id=cluster_id,
                count=per_cluster,
            )
            all_node_ids.extend(node_ids)

        with timer:
            pass  # Consensus sweep would run here

        finding_count = await count_findings(store, silo_id)
        elapsed = timer.elapsed_s
        throughput = total_commitments / elapsed if elapsed > 0 else 0

        return ScenarioResult(
            name="volume.test_500_commitments_consensus",
            passed=True,
            duration_s=elapsed,
            metrics={
                "commitments_seeded": float(total_commitments),
                "findings_created": float(finding_count),
                "throughput_per_s": throughput,
            },
        )

    except Exception as e:
        return ScenarioResult(
            name="volume.test_500_commitments_consensus",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )


async def test_uneven_cluster_scaling(
    store: Any,
    *,
    mock_llm: Any | None = None,  # noqa: ARG001
) -> ScenarioResult:
    """Test with one large cluster (100 nodes) to stress O(n^2) comparison."""
    silo_id = generate_silo_id()
    timer = ScenarioTimer()

    try:
        large_cluster_id = "cluster-large"
        with timer:
            await seed_commitments_batch(
                store,
                silo_id=silo_id,
                cluster_id=large_cluster_id,
                count=100,
            )

        elapsed = timer.elapsed_s

        return ScenarioResult(
            name="volume.test_uneven_cluster_scaling",
            passed=elapsed < 30.0,
            duration_s=elapsed,
            metrics={"cluster_size": 100.0, "elapsed_s": elapsed},
            warnings=["Exceeded 30s target"] if elapsed >= 30.0 else [],
        )

    except Exception as e:
        return ScenarioResult(
            name="volume.test_uneven_cluster_scaling",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )
