"""Dagster schedule definitions for context-service.

Consolidated into logical DAG chains that respect asset dependencies.
Schedules yield one RunRequest per active silo by querying Memgraph at
evaluation time.

Chains:
- custodian_pipeline: custodian_visit -> custodian_finalize (15min)
- knowledge_pipeline: claim_to_fact_promotion -> pattern_detection -> llm_pattern_detection (hourly)
- clustering_pipeline: clustering -> chain_stitch -> proposal_detection (daily 04:00)
- heat_pipeline: heat -> edge_heat -> weak_link_review (daily 02:00)
- maintenance: independent cleanup jobs (various schedules)
"""

from collections.abc import Iterator
from typing import Any

import dagster as dg
from dagster import ScheduleEvaluationContext

from context_service.pipelines.resources import MemgraphResource

_LIST_ACTIVE_SILOS = """
MATCH (d:Document)
RETURN DISTINCT d.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_CUSTODIAN_WORK = """
MATCH (d:Document)
WHERE d.processed_at IS NULL
   OR d.embedded_at IS NULL
RETURN DISTINCT d.silo_id AS silo_id
"""

_SILOS_WITH_PENDING_SYNTHESIZER_WORK = """
MATCH (c:Cluster)
WHERE NOT EXISTS { MATCH (c)<-[:SYNTHESIZED_FROM]-(:Belief) }
RETURN DISTINCT c.silo_id AS silo_id
UNION
MATCH (b:Belief)
WHERE b.wisdom_status IS NULL OR b.wisdom_status <> 'stale'
WITH b, [word IN split(toLower(b.content), ' ') WHERE size(word) > 4] AS words
UNWIND words AS subject
WITH b.silo_id AS silo_id, subject, count(b) AS cnt
WHERE cnt >= 2
RETURN DISTINCT silo_id
"""

_SILOS_WITH_PENDING_GROUNDSKEEPER_WORK = """
MATCH (n:Fact|Belief|Claim)
WHERE n.silo_id IS NOT NULL
  AND (n.heat_updated_at IS NULL
       OR n.heat_updated_at < datetime() - duration('PT1H'))
RETURN DISTINCT n.silo_id AS silo_id
LIMIT 50
"""


def _fetch_silo_ids(memgraph: MemgraphResource) -> list[str]:
    """Fetch all silo IDs with documents."""
    from context_service.pipelines.utils import run_async

    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(_LIST_ACTIVE_SILOS, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    return run_async(_run())


def _fetch_silos_with_pending_work(
    memgraph: MemgraphResource,
    query: str,
) -> list[str]:
    """Fetch silo IDs that have pending work based on query."""
    from context_service.pipelines.utils import run_async

    async def _run() -> list[str]:
        from context_service.stores import MemgraphClient

        driver = await memgraph.driver()
        client = MemgraphClient(driver)
        rows = await client.execute_query(query, {})
        return [str(r["silo_id"]) for r in rows if r.get("silo_id")]

    return run_async(_run())


# -----------------------------------------------------------------------------
# Core Pipeline Chains
# -----------------------------------------------------------------------------


@dg.schedule(
    cron_schedule="*/15 * * * *",
    name="custodian_pipeline_schedule",
    target=dg.AssetSelection.assets("custodian_visit", "custodian_finalize"),
    description="Every 15 minutes: custodian visit + finalize chain per active silo.",
    execution_timezone="UTC",
)
def custodian_pipeline_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Custodian pipeline: visit -> finalize."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"custodian_pipeline:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 * * * *",
    name="knowledge_pipeline_schedule",
    target=dg.AssetSelection.assets(
        "claim_to_fact_promotion",
        "causal_transitivity",
        "pattern_detection",
        "llm_pattern_detection",
    ),
    description="Hourly knowledge promotion chain: fact promotion -> patterns -> LLM patterns.",
    execution_timezone="UTC",
)
def knowledge_pipeline_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Knowledge pipeline: promotion -> pattern detection -> LLM patterns."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"knowledge_pipeline:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 4 * * *",
    name="clustering_pipeline_schedule",
    target=dg.AssetSelection.assets(
        "clustering",
        "chain_stitch",
        "proposal_detection",
    ),
    description="Daily (04:00 UTC) clustering chain: clustering -> chain_stitch -> proposal_detection.",
    execution_timezone="UTC",
)
def clustering_pipeline_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Clustering pipeline: clustering -> chain_stitch -> proposal_detection."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"clustering_pipeline:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 2 * * *",
    name="heat_pipeline_schedule",
    target=dg.AssetSelection.assets("heat", "edge_heat", "weak_link_review"),
    description="Daily (02:00 UTC) heat chain: heat -> edge_heat -> weak_link_review.",
    execution_timezone="UTC",
)
def heat_pipeline_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Heat pipeline: heat -> edge_heat -> weak_link_review."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"heat_pipeline:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


# -----------------------------------------------------------------------------
# Maintenance Schedules (independent)
# -----------------------------------------------------------------------------


@dg.schedule(
    cron_schedule="0 * * * *",
    name="reasoning_compaction_schedule",
    target=dg.AssetSelection.assets("reasoning_compaction"),
    description="Hourly reasoning-chain compaction per active silo.",
    execution_timezone="UTC",
)
def reasoning_compaction_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Compaction of reasoning chains."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"reasoning_compaction:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 3 * * *",
    name="retention_schedule",
    target=dg.AssetSelection.assets("retention_sweep"),
    description="Daily retention sweep (03:00 UTC) per active silo.",
    execution_timezone="UTC",
)
def retention_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Retention sweep for expired nodes."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"retention:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="*/30 * * * *",
    name="auto_tagging_schedule",
    target=dg.AssetSelection.assets("auto_tagging"),
    description="Tag refinement every 30 minutes per active silo.",
    execution_timezone="UTC",
)
def auto_tagging_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Auto-tagging refinement."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"auto_tagging:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="0 3 * * *",
    name="tag_maintenance_schedule",
    target=dg.AssetSelection.assets("tag_maintenance"),
    description="Daily tag vocabulary pruning (03:00 UTC) per active silo.",
    execution_timezone="UTC",
)
def tag_maintenance_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Tag vocabulary maintenance."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"tag_maintenance:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
            tags={"dagster/concurrency_key": silo_id},
        )


@dg.schedule(
    cron_schedule="*/15 * * * *",
    name="reconciliation_gc_schedule",
    target=dg.AssetSelection.assets("reconciliation_gc"),
    description="Every 15 minutes: re-reconcile orphaned chains and clean dangling Postgres rows.",
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
)
def proposal_cleanup_schedule(
    context: ScheduleEvaluationContext,
    memgraph: MemgraphResource,
) -> Iterator[dg.RunRequest]:
    """Cleanup expired ProposedBeliefs."""
    silo_ids = _fetch_silo_ids(memgraph)
    for silo_id in silo_ids:
        yield dg.RunRequest(
            run_key=f"proposal_cleanup:{silo_id}:{context.scheduled_execution_time.isoformat()}",
            partition_key=silo_id,
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


all_schedules: list[Any] = [
    # Core pipelines
    custodian_pipeline_schedule,
    knowledge_pipeline_schedule,
    clustering_pipeline_schedule,
    heat_pipeline_schedule,
    # Maintenance
    reasoning_compaction_schedule,
    retention_schedule,
    auto_tagging_schedule,
    tag_maintenance_schedule,
    reconciliation_gc_schedule,
    proposal_cleanup_schedule,
    groundskeeper_gc_schedule,
]

__all__ = [
    "all_schedules",
    "custodian_pipeline_schedule",
    "knowledge_pipeline_schedule",
    "clustering_pipeline_schedule",
    "heat_pipeline_schedule",
    "reasoning_compaction_schedule",
    "retention_schedule",
    "auto_tagging_schedule",
    "tag_maintenance_schedule",
    "reconciliation_gc_schedule",
    "proposal_cleanup_schedule",
    "groundskeeper_gc_schedule",
]
