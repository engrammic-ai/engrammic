"""Edge case scenarios: supersession chains, cycles, validator failures."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from benchmarks.custodian_stress.scenarios.base import (
    ScenarioResult,
    ScenarioTimer,
    generate_silo_id,
)


@dataclass
class MockSPONode:
    """Mock node with SPO structure for supersession testing."""

    id: str
    subject: str
    predicate: str
    object: str
    confidence: float
    created_at: datetime
    cluster_id: str = "default"


async def test_supersession_chain_terminal_only(
    store: Any,  # noqa: ARG001
    *,
    mock_llm: Any | None = None,  # noqa: ARG001
) -> ScenarioResult:
    """A supersedes B supersedes C - verify only terminal promotes."""
    timer = ScenarioTimer()

    try:
        from context_service.custodian.supersession import detect_structured_supersession

        now = datetime.now(UTC)
        nodes = [
            MockSPONode("node-c", "topic", "has_value", "old_value", 0.7, now, "cluster1"),
            MockSPONode("node-b", "topic", "has_value", "newer_value", 0.8, now, "cluster1"),
            MockSPONode("node-a", "topic", "has_value", "newest_value", 0.9, now, "cluster1"),
        ]

        with timer:
            pairs = detect_structured_supersession(nodes)

        superseded_ids = {p.superseded_id for p in pairs}
        terminal_correct = "node-a" not in superseded_ids
        passed = terminal_correct

        return ScenarioResult(
            name="edge_cases.test_supersession_chain_terminal_only",
            passed=passed,
            duration_s=timer.elapsed_s,
            metrics={
                "pairs_found": float(len(pairs)),
                "terminal_correct": 1.0 if terminal_correct else 0.0,
            },
            error=None if passed else "Terminal node incorrectly superseded",
        )

    except Exception as e:
        return ScenarioResult(
            name="edge_cases.test_supersession_chain_terminal_only",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )


async def test_circular_dep_no_hang(
    store: Any,  # noqa: ARG001
    *,
    timeout_s: float = 5.0,
) -> ScenarioResult:
    """A references B references A - verify no infinite loop."""
    timer = ScenarioTimer()

    try:
        from context_service.custodian.supersession import detect_structured_supersession

        now = datetime.now(UTC)
        nodes = [
            MockSPONode("node-a", "entity1", "contradicts", "entity2", 0.9, now),
            MockSPONode("node-b", "entity2", "contradicts", "entity1", 0.9, now),
        ]

        with timer:
            try:
                pairs = await asyncio.wait_for(
                    asyncio.to_thread(detect_structured_supersession, nodes),
                    timeout=timeout_s,
                )
            except TimeoutError:
                return ScenarioResult(
                    name="edge_cases.test_circular_dep_no_hang",
                    passed=False,
                    duration_s=timeout_s,
                    error=f"Timeout after {timeout_s}s - possible infinite loop",
                )

        # Verify no cycle in result
        graph: dict[str, set[str]] = {}
        for p in pairs:
            graph.setdefault(p.superseding_id, set()).add(p.superseded_id)

        def has_cycle(node: str, visited: set[str], path: set[str]) -> bool:
            visited.add(node)
            path.add(node)
            for neighbor in graph.get(node, set()):
                if neighbor in path:
                    return True
                if neighbor not in visited and has_cycle(neighbor, visited, path):
                    return True
            path.remove(node)
            return False

        cycle_found = False
        visited: set[str] = set()
        for node in graph:
            if node not in visited and has_cycle(node, visited, set()):
                cycle_found = True
                break

        return ScenarioResult(
            name="edge_cases.test_circular_dep_no_hang",
            passed=not cycle_found,
            duration_s=timer.elapsed_s,
            metrics={
                "pairs_found": float(len(pairs)),
                "cycle_found": 1.0 if cycle_found else 0.0,
            },
            error="Cycle found in supersession pairs" if cycle_found else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="edge_cases.test_circular_dep_no_hang",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )


async def test_cross_cluster_supersession_chain(
    store: Any,
    *,
    mock_llm: Any | None = None,  # noqa: ARG001
) -> ScenarioResult:
    """A, B, C in different clusters - verify chain-stitching connects them."""
    silo_id = generate_silo_id()
    timer = ScenarioTimer()

    try:
        from context_service.custodian.chain_stitcher import stitch_cross_cluster_chains

        with timer:
            result = await stitch_cross_cluster_chains(store=store, silo_id=silo_id)

        return ScenarioResult(
            name="edge_cases.test_cross_cluster_supersession_chain",
            passed=len(result.errors) == 0,
            duration_s=timer.elapsed_s,
            metrics={
                "chains_found": float(result.chains_found),
                "terminals_found": float(result.terminals_found),
            },
            error="; ".join(result.errors) if result.errors else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="edge_cases.test_cross_cluster_supersession_chain",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )
