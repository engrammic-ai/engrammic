"""Dagster sensors for context-service."""

from typing import Any

from context_service.pipelines.sensors.belief_merge import belief_merge_sensor
from context_service.pipelines.sensors.belief_synthesis import belief_synthesis_sensor
from context_service.pipelines.sensors.belief_synthesis_sensor import (
    memory_cluster_belief_sensor,
)
from context_service.pipelines.sensors.cascade_review import cascade_review_sensor
from context_service.pipelines.sensors.causal_chain_sensor import (
    causal_transitivity_sensor,
    chain_stitch_sensor,
)
from context_service.pipelines.sensors.confidence_drift import confidence_drift_sensor
from context_service.pipelines.sensors.document_arrival import document_arrival_sensor
from context_service.pipelines.sensors.outbox_embed_sensor import outbox_embed_sensor
from context_service.pipelines.sensors.poison_queue_sensor import poison_queue_sensor
from context_service.pipelines.sensors.session_autoclose import session_autoclose_sensor

all_sensors: list[Any] = [
    document_arrival_sensor,
    outbox_embed_sensor,
    poison_queue_sensor,
    belief_synthesis_sensor,
    confidence_drift_sensor,
    session_autoclose_sensor,
    causal_transitivity_sensor,
    chain_stitch_sensor,
    belief_merge_sensor,
    cascade_review_sensor,
    memory_cluster_belief_sensor,
]
