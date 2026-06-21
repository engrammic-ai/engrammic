"""Dagster schedule definitions for context-service.

SAGE (Synthesis, Aggregation, and Graph Evolution) schedules:
- sage_groundskeeper_schedule: heat and maintenance (every 15 minutes, pending-work gated)
- sage_validator_schedule: contradiction + stale commitment checks (every 5m, pending-work gated)

Maintenance schedules:
- reasoning_compaction_schedule: every 2h (pending-work gated)
- daily_maintenance_schedule: daily 03:00 (retention + tag pruning)
- auto_tagging_schedule: every 4h (pending-work gated)
- reconciliation_gc_schedule: hourly (global, single run)
- proposal_cleanup_schedule: daily 06:00 (pending-work gated)
- groundskeeper_gc_schedule: nightly 01:00 (global, single run)

Pending-work gated schedules only fire RunRequests for silos with actual work,
reducing job count from O(N silos) to O(silos with work).
"""

from collections.abc import Iterator
from typing import Any

import dagster as dg
from dagster import ScheduleEvaluationContext

from context_service.pipelines.jobs.beacon_sender import beacon_sender_job
from context_service.pipelines.jobs.telemetry_gauges import telemetry_gauges_job
from context_service.pipelines.jobs.telemetry_prune import telemetry_prune_job
from context_service.pipelines.partitions import silo_partitions
from context_service.pipelines.resources import MemgraphResource

_LIST_ACTIVE_SILOS = """
MATCH (d:Document)
RETURN DISTINCT d.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_GROUNDSKEEPER_WORK = """
MATCH (n:Fact|Belief|Claim)
WHERE n.silo_id IS NOT NULL
  AND n.created_at > datetime() - duration('PT2H')
  AND (n.heat_updated_at IS NULL
       OR n.heat_updated_at < datetime() - duration('PT1H'))
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 50
"""

_SILOS_WITH_PENDING_COMPACTION = """
MATCH (c:ReasoningChain)
WHERE c.status IN ['published', 'retracted']
  AND c.compacted_at IS NULL
RETURN DISTINCT c.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_TAGGING = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
  AND n.content IS NOT NULL
  AND n.auto_tagged_at IS NULL
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 100
"""

_SILOS_WITH_EXPIRED_PROPOSALS = """
MATCH (p:ProposedBelief)
WHERE p.expires_at < datetime()
RETURN DISTINCT p.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_VALIDATION = """
MATCH (n)
WHERE n.silo_id IS NOT NULL
  AND n.contradiction_candidate = true
RETURN DISTINCT n.silo_id AS silo_id
UNION
MATCH (n:Commitment)
WHERE n.silo_id IS NOT NULL
  AND (n.stale_checked_at IS NULL
       OR n.stale_checked_at < datetime() - duration('PT5M'))
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 50
"""


def _fetch_silo_ids(memgraph: MemgraphResource) -> list[str]:
    """Fetch all silo IDs with documents."""
    import structlog

    from context_service.pipelines.utils import run_async

    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    try:
        return list(run_async(_run()))
    except Exception:
        log = structlog.get_logger()
        log.warning("schedule_silo_fetch_failed", query_preview=_LIST_ACTIVE_SILOS[:50])
        return []


def _fetch_silos_with_pending_work(
    memgraph: MemgraphResource,
    query: str,
) -> list[str]:
    """Fetch silo IDs that have pending work based on query."""
    import structlog

    from context_service.pipelines.utils import run_async

    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(query, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    try:
        return list(run_async(_run()))
    except Exception:
        log = structlog.get_logger()
        log.warning("schedule_silo_fetch_failed", query_preview=query[:50])
        return []


def _ensure_partition_exists(
    context: ScheduleEvaluationContext,
    silo_id: str,
) -> None:
    """Register silo_id as a dynamic partition if not already present.

    Must be called BEFORE yielding RunRequest, as Dagster validates partition
    keys synchronously before processing dynamic_partitions_requests.
    """
    partitions_def_name = silo_partitions.name or "silo_id"
    existing = context.instance.get_dynamic_partitions(partitions_def_name)
    if silo_id not in existing:
        context.instance.add_dynamic_partitions(partitions_def_name, [silo_id])


def _run_request_with_partition(
    silo_id: str,
    run_key: str,
    tags: dict[str, str] | None = None,
) -> dg.RunRequest:
    """Create RunRequest for a silo partition.

    Note: Call _ensure_partition_exists() before this to register the partition.
    """
    return dg.RunRequest(
        run_key=run_key,
        partition_key=silo_id,
        tags=tags or {},
    )


# -----------------------------------------------------------------------------
# Core Pipeline Chains
# -----------------------------------------------------------------------------


@dg.schedule(
    cron_schedule="0 * * * *",
    name="sage_groundskeeper_schedule",
    target=dg.AssetSelection.assets(
        "heat",
        "edge_heat",
        "heat_diffusion",
        "prewarm_sweep",
    ),
    # DEPRECATED: Replaced by groundskeeper_sensor which triggers on actual events.
    # Kept for fallback if sensor has issues.
    description="SAGE Groundskeeper (hourly): heat and maintenance. DEPRECATED - use sensor.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.STOPPED,
)
def sage_groundskeeper_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """SAGE Groundskeeper: heat and maintenance for silos with stale scores."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_GROUNDSKEEPER_WORK)

    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"sage_groundskeeper:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"sage_job": "groundskeeper", "dagster/concurrency_key": silo_id},
        )


# -----------------------------------------------------------------------------
# Maintenance Schedules (independent)
# -----------------------------------------------------------------------------


@dg.schedule(
    cron_schedule="0 */2 * * *",
    name="reasoning_compaction_schedule",
    target=dg.AssetSelection.assets("reasoning_compaction"),
    description="Reasoning-chain compaction every 2h for silos with pending work.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def reasoning_compaction_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Compaction of reasoning chains for silos with finished chains."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_COMPACTION)
    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"reasoning_compaction:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 3 * * *",
    name="daily_maintenance_schedule",
    target=dg.AssetSelection.assets("retention_sweep", "tag_maintenance"),
    description="Daily maintenance (03:00 UTC): retention sweep + tag pruning per silo.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def daily_maintenance_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Combined daily maintenance: retention + tag pruning.

    Runs for all active silos. Assets have fast-exit logic for silos
    with no work (no retention policy / no dynamic tags).
    """
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"daily_maintenance:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"dagster/concurrency_key": silo_id, "schedule_type": "maintenance"},
        )


@dg.schedule(
    cron_schedule="0 */4 * * *",
    name="auto_tagging_schedule",
    target=dg.AssetSelection.assets("auto_tagging"),
    description="Tag refinement every 4h for silos with untagged nodes.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def auto_tagging_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Auto-tagging for silos with nodes needing tags."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_TAGGING)
    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"auto_tagging:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 * * * *",
    name="reconciliation_gc_schedule",
    target=dg.AssetSelection.assets("reconciliation_gc"),
    description="Hourly: re-reconcile orphaned chains and clean dangling Postgres rows.",
    execution_timezone="UTC",
)
def reconciliation_gc_schedule(
    context: ScheduleEvaluationContext,
) -> dg.RunRequest:
    """Global reconciliation GC sweep."""
    return dg.RunRequest(
        run_key=f"reconciliation_gc:{context.scheduled_execution_time.isoformat()}",
    )


@dg.schedule(
    cron_schedule="0 6 * * *",
    name="proposal_cleanup_schedule",
    target=dg.AssetSelection.assets("proposal_cleanup"),
    description="Daily proposal cleanup (06:00 UTC): delete expired ProposedBeliefs.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def proposal_cleanup_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Cleanup expired ProposedBeliefs for silos with expired proposals."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_EXPIRED_PROPOSALS)
    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"proposal_cleanup:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 1 * * *",
    name="groundskeeper_gc_schedule",
    job_name="groundskeeper_nightly",
    description="Nightly memory GC (01:00 UTC): delete expired Memory-layer nodes across all silos.",
    execution_timezone="UTC",
)
def groundskeeper_gc_schedule(context: ScheduleEvaluationContext) -> dg.RunRequest:
    """Nightly Groundskeeper GC sweep."""
    return dg.RunRequest(
        run_key=f"groundskeeper_gc:{context.scheduled_execution_time.isoformat()}",
    )


@dg.schedule(
    cron_schedule="*/5 * * * *",
    name="sage_validator_schedule",
    target=dg.AssetSelection.assets(
        "validator_contradiction",
        "validator_stale_commitment",
        "marker_cleanup",
    ),
    description="SAGE Validator (every 5m): contradiction confirmation, stale commitment detection, and marker cleanup.",
    execution_timezone="UTC",
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def sage_validator_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """SAGE Validator: run contradiction and stale-commitment checks for silos with pending work."""
    silo_ids = _fetch_silos_with_pending_work(memgraph, _SILOS_WITH_PENDING_VALIDATION)

    for silo_id in silo_ids:
        _ensure_partition_exists(context, silo_id)
        yield _run_request_with_partition(
            silo_id=silo_id,
            run_key=f"sage_validator:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            tags={"sage_job": "validator", "dagster/concurrency_key": silo_id},
        )


telemetry_gauges_schedule = dg.ScheduleDefinition(
    job=telemetry_gauges_job,
    cron_schedule="0 * * * *",  # hourly
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

telemetry_prune_schedule = dg.ScheduleDefinition(
    job=telemetry_prune_job,
    cron_schedule="0 3 * * *",  # daily at 3am
    default_status=dg.DefaultScheduleStatus.RUNNING,
)

beacon_sender_schedule = dg.ScheduleDefinition(
    job=beacon_sender_job,
    cron_schedule="0 * * * *",  # hourly (matches beacon_interval_hours default)
    default_status=dg.DefaultScheduleStatus.STOPPED,  # opt-in for self-hosted
)

all_schedules: list[Any] = [
    # SAGE pipelines
    sage_groundskeeper_schedule,
    sage_validator_schedule,
    # Maintenance
    reasoning_compaction_schedule,
    daily_maintenance_schedule,
    auto_tagging_schedule,
    reconciliation_gc_schedule,
    proposal_cleanup_schedule,
    groundskeeper_gc_schedule,
    # Telemetry
    telemetry_gauges_schedule,
    telemetry_prune_schedule,
    beacon_sender_schedule,
]

__all__ = [
    "all_schedules",
    "sage_groundskeeper_schedule",
    "sage_validator_schedule",
    "reasoning_compaction_schedule",
    "daily_maintenance_schedule",
    "auto_tagging_schedule",
    "reconciliation_gc_schedule",
    "proposal_cleanup_schedule",
    "groundskeeper_gc_schedule",
    "telemetry_gauges_schedule",
    "telemetry_prune_schedule",
    "beacon_sender_schedule",
]
