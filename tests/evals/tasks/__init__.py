"""Task functions for eval scenarios."""

from tests.evals.tasks.direct import (
    claim_promotion_task,
    cross_layer_task,
    evidence_validation_task,
    freshness_task,
    latency_task,
    link_semantics_task,
    provenance_task,
    reasoning_coherence_task,
    recall_task,
    reflection_task,
    silo_isolation_task,
    time_travel_task,
)

__all__ = [
    "recall_task",
    "claim_promotion_task",
    "cross_layer_task",
    "freshness_task",
    "provenance_task",
    "reflection_task",
    "silo_isolation_task",
    "evidence_validation_task",
    "reasoning_coherence_task",
    "time_travel_task",
    "link_semantics_task",
    "latency_task",
]
