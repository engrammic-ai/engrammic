"""Sensor to retry failed summarizations."""

from __future__ import annotations

from collections.abc import Iterator

import dagster as dg
from dagster import SensorEvaluationContext

# Query used when the resummarization asset is wired up.
FIND_PENDING_SUMMARIZATIONS = """
MATCH (e:Event {silo_id: $silo_id})
WHERE e.event_type = 'reasoning_trace'
  AND e.summarization_pending = true
RETURN e.id AS id, e.source_chain_id AS chain_id
LIMIT 10
"""


@dg.sensor(
    name="summarization_retry_sensor",
    minimum_interval_seconds=300,
    description="Retry Events with pending summarization.",
)
def summarization_retry_sensor(
    context: SensorEvaluationContext,
) -> Iterator[dg.RunRequest]:
    """Find Events with pending summarization and log them.

    Note: Full retry implementation requires a resummarization asset.
    This sensor identifies pending work for monitoring.
    """
    # For now, just log pending counts - full retry needs a dedicated asset
    context.log.info("Checking for pending summarizations")
    # Implementation would query and yield RunRequests
    return iter([])  # Placeholder - no RunRequests until asset exists
