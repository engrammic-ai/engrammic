"""Validator Dagster job.

Combines contradiction confirmation, stale commitment detection, and marker
cleanup into a single asset-based job. Runs on a 5-minute schedule.
"""

from __future__ import annotations

import dagster as dg

sage_validator_job = dg.define_asset_job(
    name="sage_validator_job",
    selection=dg.AssetSelection.assets(
        "validator_contradiction_asset",
        "validator_stale_commitment_asset",
        "marker_cleanup_asset",
    ),
    description="SAGE Validator: contradiction confirmation, stale commitment detection, and marker cleanup.",
)
