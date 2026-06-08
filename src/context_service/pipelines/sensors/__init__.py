"""Dagster sensors for context-service.

Event-driven sensors that trigger runs based on actual work rather than polling.
"""

from typing import Any

from context_service.pipelines.sensors.cascade_review import cascade_review_sensor
from context_service.pipelines.sensors.groundskeeper_sensor import groundskeeper_sensor
from context_service.pipelines.sensors.poison_queue_sensor import poison_queue_sensor
from context_service.pipelines.sensors.reaction_health import (
    reaction_dlq_sensor,
    reaction_queue_depth_sensor,
)

all_sensors: list[Any] = [
    poison_queue_sensor,
    cascade_review_sensor,
    reaction_queue_depth_sensor,
    reaction_dlq_sensor,
    groundskeeper_sensor,
]
