"""Dagster sensors for context-service.

Most sensors have been consolidated into SAGE schedules.
Remaining sensors handle edge cases not suitable for scheduled execution.
"""

from typing import Any

from context_service.pipelines.sensors.cascade_review import cascade_review_sensor
from context_service.pipelines.sensors.poison_queue_sensor import poison_queue_sensor

all_sensors: list[Any] = [
    poison_queue_sensor,
    cascade_review_sensor,
]
