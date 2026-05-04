"""Base classes and helpers for stress testing scenarios."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class ScenarioResult:
    """Result of a single stress test scenario."""

    name: str
    passed: bool
    duration_s: float
    metrics: dict[str, float] = field(default_factory=dict)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def generate_silo_id() -> str:
    """Generate a unique silo ID for test isolation."""
    return f"stress-test-{uuid.uuid4()}"


async def seed_commitment(
    store: Any,
    *,
    silo_id: str,
    cluster_id: str,
    content: str,
    confidence: float = 0.85,
    status: str = "pending",
) -> str:
    """Seed a single Commitment node for testing."""
    node_id = str(uuid.uuid4())
    query = """
    CREATE (c:Commitment {
        id: $node_id,
        silo_id: $silo_id,
        cluster_id: $cluster_id,
        content: $content,
        confidence: $confidence,
        status: $status,
        created_at: datetime()
    })
    RETURN c.id AS id
    """
    await store.run_query(
        query,
        {
            "node_id": node_id,
            "silo_id": silo_id,
            "cluster_id": cluster_id,
            "content": content,
            "confidence": confidence,
            "status": status,
        },
    )
    return node_id


async def seed_commitments_batch(
    store: Any,
    *,
    silo_id: str,
    cluster_id: str,
    count: int,
    confidence: float = 0.85,
) -> list[str]:
    """Seed multiple Commitment nodes in a batch."""
    node_ids = [str(uuid.uuid4()) for _ in range(count)]
    query = """
    UNWIND $nodes AS node
    CREATE (c:Commitment {
        id: node.id,
        silo_id: $silo_id,
        cluster_id: $cluster_id,
        content: node.content,
        confidence: $confidence,
        status: 'pending',
        created_at: datetime()
    })
    """
    nodes = [{"id": nid, "content": f"Test commitment {i}"} for i, nid in enumerate(node_ids)]
    await store.run_query(
        query,
        {
            "nodes": nodes,
            "silo_id": silo_id,
            "cluster_id": cluster_id,
            "confidence": confidence,
        },
    )
    return node_ids


async def count_findings(store: Any, silo_id: str) -> int:
    """Count Finding nodes in a silo."""
    query = "MATCH (f:Finding {silo_id: $silo_id}) RETURN count(f) AS cnt"
    result = await store.run_query(query, {"silo_id": silo_id})
    return result[0]["cnt"] if result else 0


async def count_supersedes_edges(store: Any, silo_id: str) -> int:
    """Count SUPERSEDES edges in a silo."""
    query = """
    MATCH (a {silo_id: $silo_id})-[r:SUPERSEDES]->(b {silo_id: $silo_id})
    RETURN count(r) AS cnt
    """
    result = await store.run_query(query, {"silo_id": silo_id})
    return result[0]["cnt"] if result else 0


class ScenarioTimer:
    """Context manager for timing scenario execution."""

    def __init__(self) -> None:
        self.start_time: float = 0
        self.end_time: float = 0

    def __enter__(self) -> ScenarioTimer:
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args: Any) -> None:
        self.end_time = time.perf_counter()

    @property
    def elapsed_s(self) -> float:
        return self.end_time - self.start_time


async def run_scenario(
    name: str,
    scenario_fn: Callable[[], Coroutine[Any, Any, dict[str, float]]],
) -> ScenarioResult:
    """Run a scenario function and wrap result in ScenarioResult."""
    timer = ScenarioTimer()
    try:
        with timer:
            metrics = await scenario_fn()
        return ScenarioResult(
            name=name,
            passed=True,
            duration_s=timer.elapsed_s,
            metrics=metrics,
        )
    except AssertionError as e:
        return ScenarioResult(
            name=name,
            passed=False,
            duration_s=timer.elapsed_s,
            error=str(e),
        )
    except Exception as e:
        return ScenarioResult(
            name=name,
            passed=False,
            duration_s=timer.elapsed_s,
            error=f"{type(e).__name__}: {e}",
        )
