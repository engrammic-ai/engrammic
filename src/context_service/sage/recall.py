"""Sage recall: Query transactions with epistemic-aware scoring.

Implements the recall pipeline for Phase 6 of the brain architecture.
Provides dataclasses, options, and scoring constants for retrieval.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from context_service.sage.transactions import ClusterState, NodeState, SynthesisState

if TYPE_CHECKING:
    pass

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
