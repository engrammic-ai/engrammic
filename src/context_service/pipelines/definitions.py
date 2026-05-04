"""Top-level Dagster definitions for context-service.

Loaded via `dagster-webserver -m context_service.pipelines.definitions` and
`dagster-daemon run -m context_service.pipelines.definitions`.
"""

from __future__ import annotations

import dagster as dg

from context_service.pipelines.assets import all_assets
from context_service.pipelines.resources import build_default_resources
from context_service.pipelines.schedules import all_schedules
from context_service.pipelines.sensors import all_sensors

causal_tombstone_job = dg.define_asset_job(
    name="causal_tombstone_job",
    selection=dg.AssetSelection.assets("causal_tombstone"),
    description="Manual tombstone run - supply silo_id and filter config at launch.",
)

defs = dg.Definitions(
    assets=all_assets,
    jobs=[causal_tombstone_job],
    schedules=all_schedules,
    sensors=all_sensors,
    resources=build_default_resources(),
)
