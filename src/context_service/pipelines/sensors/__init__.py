"""Dagster sensors for context-service."""

from typing import Any

from context_service.pipelines.sensors.belief_synthesis import belief_synthesis_sensor
from context_service.pipelines.sensors.document_arrival import document_arrival_sensor
from context_service.pipelines.sensors.poison_queue_sensor import poison_queue_sensor
from context_service.pipelines.sensors.summarization_retry import summarization_retry_sensor

all_sensors: list[Any] = [
    document_arrival_sensor,
    poison_queue_sensor,
    belief_synthesis_sensor,
    summarization_retry_sensor,
]
