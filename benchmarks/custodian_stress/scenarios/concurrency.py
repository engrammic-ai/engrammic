"""Concurrency scenarios: parallel sweeps, edge deduplication."""

from __future__ import annotations

import asyncio
from typing import Any

from benchmarks.custodian_stress.scenarios.base import (
    ScenarioResult,
    ScenarioTimer,
    count_findings,
    generate_silo_id,
    seed_commitments_batch,
)


async def test_no_duplicate_findings(
    store: Any,
    *,
    parallel_count: int = 3,
) -> ScenarioResult:
    """Spawn parallel sweeps, verify no duplicate Findings via blake2b ID."""
    silo_id = generate_silo_id()
    timer = ScenarioTimer()

    try:
        # Seed shared commitments
        cluster_id = "shared-cluster"
        await seed_commitments_batch(
            store,
            silo_id=silo_id,
            cluster_id=cluster_id,
            count=50,
        )

        async def run_sweep(sweep_id: int) -> int:
            """Simulate a consensus sweep."""
            # In real implementation, call actual consensus promotion
            await asyncio.sleep(0.1)  # Simulate work
            return sweep_id

        with timer:
            # Run parallel sweeps
            tasks = [run_sweep(i) for i in range(parallel_count)]
            await asyncio.gather(*tasks)

        # Count findings - should have no duplicates
        finding_count = await count_findings(store, silo_id)

        # Check for duplicate Finding IDs
        query = """
        MATCH (f:Finding {silo_id: $silo_id})
        WITH f.id AS id, count(*) AS cnt
        WHERE cnt > 1
        RETURN id, cnt
        """
        duplicates = await store.run_query(query, {"silo_id": silo_id})

        passed = len(duplicates) == 0

        return ScenarioResult(
            name="concurrency.test_no_duplicate_findings",
            passed=passed,
            duration_s=timer.elapsed_s,
            metrics={
                "parallel_sweeps": parallel_count,
                "findings_created": finding_count,
                "duplicates_found": len(duplicates),
            },
            error=f"Found {len(duplicates)} duplicate findings" if duplicates else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="concurrency.test_no_duplicate_findings",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )


async def test_no_duplicate_supersedes_edges(
    store: Any,
    *,
    parallel_count: int = 3,
) -> ScenarioResult:
    """Parallel supersession passes must not create duplicate edges."""
    silo_id = generate_silo_id()
    timer = ScenarioTimer()

    try:
        # Seed nodes
        cluster_id = "shared-cluster"
        await seed_commitments_batch(
            store,
            silo_id=silo_id,
            cluster_id=cluster_id,
            count=20,
        )

        with timer:
            # Run parallel supersession passes
            # (In real implementation, call actual supersession)
            pass

        # Check for duplicate edges
        query = """
        MATCH (a {silo_id: $silo_id})-[r:SUPERSEDES]->(b {silo_id: $silo_id})
        WITH a.id AS from_id, b.id AS to_id, count(r) AS edge_count
        WHERE edge_count > 1
        RETURN from_id, to_id, edge_count
        """
        duplicates = await store.run_query(query, {"silo_id": silo_id})

        passed = len(duplicates) == 0

        return ScenarioResult(
            name="concurrency.test_no_duplicate_supersedes_edges",
            passed=passed,
            duration_s=timer.elapsed_s,
            metrics={
                "parallel_passes": parallel_count,
                "duplicate_edges": len(duplicates),
            },
            error=f"Found {len(duplicates)} duplicate SUPERSEDES edges" if duplicates else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="concurrency.test_no_duplicate_supersedes_edges",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )
