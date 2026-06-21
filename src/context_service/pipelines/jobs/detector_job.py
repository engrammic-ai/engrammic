"""Detector Dagster job.

Combines contradiction detection, supports detection, stale commitment detection,
and marker cleanup into a single asset-based job. Runs on a 5-minute schedule.
"""

from __future__ import annotations

import dagster as dg

sage_detector_job = dg.define_asset_job(
    name="sage_detector_job",
    selection=dg.AssetSelection.assets(
        "detect_contradicts",
        "detect_supports",
        "detect_stale_commitment",
        "marker_cleanup",
    ),
    description="SAGE Detector: contradiction detection, supports detection, stale commitment detection, and marker cleanup.",
)
