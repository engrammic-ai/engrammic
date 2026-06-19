"""Visit orchestrator stub for CITE v2 schema.

CITE v2 removes cluster-based visits. This module is retained for backwards
compatibility but immediately returns SKIPPED.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from context_service.custodian.models import VisitStatus
from context_service.custodian.traces import UsageBreakdown

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.stores.redis import RedisClient

PhaseCallback = Callable[[str, str], Awaitable[None]]


@dataclass
class VisitResult:
    """Outcome of a single cluster visit."""

    cluster_id: str
    pass_id: str
    status: VisitStatus
    write_result: None = None
    usage_breakdown: dict[str, UsageBreakdown] = field(default_factory=dict)
    skipped_reason: str | None = None
    error: str | None = None


async def run_visit(
    *,
    cluster_id: str,
    org_id: str,  # noqa: ARG001
    silo_id: str,  # noqa: ARG001
    pass_id: str,
    cluster_level: str,  # noqa: ARG001
    cluster_member_count: int,  # noqa: ARG001
    naive_summary: str | None,  # noqa: ARG001
    child_finding_summaries: list[str],  # noqa: ARG001
    memgraph_client: HyperGraphStore,  # noqa: ARG001
    redis_client: RedisClient,  # noqa: ARG001
    phase_callback: PhaseCallback | None = None,  # noqa: ARG001
) -> VisitResult:
    """DEPRECATED (CITE v2): Cluster-based visits removed.

    Returns SKIPPED immediately. Retained for backwards compatibility
    with any code that still calls this function.
    """
    return VisitResult(
        cluster_id=cluster_id,
        pass_id=pass_id,
        status=VisitStatus.SKIPPED,
        skipped_reason="CITE v2: cluster-based visits deprecated",
    )


__all__ = [
    "PhaseCallback",
    "VisitResult",
    "run_visit",
]
