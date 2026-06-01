"""Sage recall: Query transactions with epistemic-aware scoring.

Implements the recall pipeline for Phase 6 of the brain architecture.
Provides dataclasses, options, and scoring constants for retrieval.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from context_service.sage.transactions import ClusterState, NodeState, SynthesisState

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Scoring constants
MEMORY_DECAY_SIGMA = 90  # days; half-life for temporal decay
MAX_GRAPH_DEPTH = 3
MAX_NEIGHBORS_PER_NODE = 20
LAZY_SYNTHESIS_TIMEOUT_MS = 2000


class Layer(StrEnum):
    """Cognitive layers for epistemic recall filtering."""

    MEMORY = "MEMORY"
    KNOWLEDGE = "KNOWLEDGE"
    WISDOM = "WISDOM"
    INTELLIGENCE = "INTELLIGENCE"


@dataclass
class RecallOptions:
    """Options controlling recall query behavior and filtering."""

    top_k: int = 10
    layers: list[Layer] | None = None
    include_superseded: bool = False
    as_of: datetime | None = None
    include_synthesis: bool = True
    min_confidence: float = 0.0
    depth: int = 0


@dataclass
class RelatedNode:
    """A node related to a recall result via a graph edge."""

    node_id: str
    edge_type: str
    direction: str  # "outgoing" | "incoming"
    depth: int
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecallResultItem:
    """A single node returned from a recall query with scoring metadata."""

    node_id: str
    content: str
    layer: Layer
    score: float
    confidence: float
    created_at: datetime
    properties: dict[str, Any] = field(default_factory=dict)
    related: list[RelatedNode] = field(default_factory=list)
    synthesized: bool = False


@dataclass
class RecallResult:
    """Aggregated result from a recall query."""

    results: list[RecallResultItem]
    total_candidates: int
    synthesis_pending: bool
    query_time_ms: float


def gaussian_decay(age_days: float, sigma: float = MEMORY_DECAY_SIGMA) -> float:
    """Apply Gaussian decay based on age. Returns value in [0, 1]."""
    return math.exp(-(age_days**2) / (2 * sigma**2))


def days_since(dt: datetime) -> float:
    """Calculate days since a datetime."""
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    delta = now - dt
    return delta.total_seconds() / 86400


def compute_recall_score(node: dict[str, Any], similarity: float, heat: float = 0.0) -> float:
    """Compute epistemic recall score for a node.

    Applies layer-specific scoring rules, heat boost, and clamps to [0, 1].
    """
    layer = node.get("layer", "")
    confidence = float(node.get("confidence", 1.0))
    created_at = node.get("created_at")

    age_days: float = 0.0
    if isinstance(created_at, datetime):
        age_days = days_since(created_at)
    elif isinstance(created_at, str):
        try:
            age_days = days_since(datetime.fromisoformat(created_at))
        except ValueError:
            age_days = 0.0

    if layer == Layer.MEMORY:
        layer_score = similarity * gaussian_decay(age_days)
    elif layer == Layer.KNOWLEDGE:
        corroboration_boost = float(node.get("corroboration_count", 0))
        layer_score = similarity * confidence * (1 + corroboration_boost * 0.2)
    elif layer == Layer.WISDOM:
        synthesis_state = node.get("synthesis_state", "")
        staleness_penalty = 0.5 if synthesis_state == SynthesisState.STALE else 1.0
        layer_score = similarity * confidence * staleness_penalty
    else:
        # INTELLIGENCE and unknown layers: no decay
        layer_score = similarity

    final_score = layer_score * (1 + heat * 0.1)
    return max(0.0, min(1.0, final_score))


async def traverse_graph(
    store: HyperGraphStore,
    node_id: str,
    silo_id: str,
    max_depth: int,
    current_depth: int = 1,
    visited: set[str] | None = None,
) -> list[RelatedNode]:
    """Traverse graph to find related nodes up to max_depth."""
    from context_service.db import queries as q

    if visited is None:
        visited = set()

    if current_depth > max_depth:
        return []

    visited.add(node_id)

    # Get immediate neighbors using TRAVERSE_NEIGHBORS query
    neighbors = await store.execute_query(
        q.TRAVERSE_NEIGHBORS,
        {
            "node_id": node_id,
            "silo_id": silo_id,
            "visited": list(visited),
            "limit": MAX_NEIGHBORS_PER_NODE,
        },
    )

    results: list[RelatedNode] = []
    for neighbor in neighbors:
        neighbor_id = neighbor.get("id")
        if neighbor_id is None:
            continue

        results.append(
            RelatedNode(
                node_id=neighbor_id,
                edge_type=neighbor.get("edge_type", "RELATED_TO"),
                direction=neighbor.get("direction", "outgoing"),
                depth=current_depth,
                properties=neighbor.get("properties", {}),
            )
        )

        # Recurse if depth allows
        if current_depth < max_depth:
            child_results = await traverse_graph(
                store=store,
                node_id=neighbor_id,
                silo_id=silo_id,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                visited=visited,
            )
            results.extend(child_results)

    return results
