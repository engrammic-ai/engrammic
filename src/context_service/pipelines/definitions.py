"""Top-level Dagster definitions for context-service.

Loaded via `dagster-webserver -m context_service.pipelines.definitions` and
`dagster-daemon run -m context_service.pipelines.definitions`.
"""

from __future__ import annotations

import dagster as dg

from context_service.pipelines.assets import all_assets
from context_service.pipelines.jobs import (
    groundskeeper_nightly,
    orphan_chain_recovery_job,
    orphan_recovery_schedule,
    reembed_migration,
    sage_decayer_job,
    sage_decayer_schedule,
    sage_detector_job,
    sage_legacy_embed_migration_job,
    sage_promoter_job,
    sage_promoter_schedule,
    sage_synthesizer_job,
    sage_synthesizer_schedule,
    source_cleanup_job,
    source_cleanup_schedule,
    spo_backfill_job,
    usage_retention_job,
    usage_retention_schedule,
)
from context_service.pipelines.jobs.telemetry_gauges import telemetry_gauges_job
from context_service.pipelines.jobs.telemetry_prune import telemetry_prune_job
from context_service.pipelines.resources import build_default_resources
from context_service.pipelines.schedules import all_schedules
from context_service.pipelines.sensors import all_sensors
from context_service.telemetry.metrics import setup_metrics

# Initialize metrics buffer at module load so LLM token tracking works in Dagster ops
setup_metrics()

causal_tombstone_job = dg.define_asset_job(
    name="causal_tombstone_job",
    selection=dg.AssetSelection.assets("causal_tombstone"),
    description="Manual tombstone run - supply silo_id and filter config at launch.",
)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[
        causal_tombstone_job,
        groundskeeper_nightly,
        orphan_chain_recovery_job,
        reembed_migration,
        sage_decayer_job,
        sage_detector_job,
        sage_legacy_embed_migration_job,
        sage_promoter_job,
        sage_synthesizer_job,
        source_cleanup_job,
        spo_backfill_job,
        telemetry_gauges_job,
        telemetry_prune_job,
        usage_retention_job,
    ],
    schedules=[
        *all_schedules,
        orphan_recovery_schedule,
        sage_decayer_schedule,
        sage_promoter_schedule,
        sage_synthesizer_schedule,
        source_cleanup_schedule,
        usage_retention_schedule,
    ],
    sensors=all_sensors,
    resources=build_default_resources(),
)
