"""Validator Dagster job.

Combines contradiction confirmation, stale commitment detection, and marker
cleanup into a single asset-based job. Runs on a 5-minute schedule.
"""

from __future__ import annotations

import dagster as dg

sage_validator_job = dg.define_asset_job(
    name="sage_validator_job",
    selection=dg.AssetSelection.assets(
        "validator_contradiction",
        "validator_stale_commitment",
        "marker_cleanup",
    ),
    description="SAGE Validator: contradiction confirmation, stale commitment detection, and marker cleanup.",
)
