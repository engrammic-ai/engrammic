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


async def recall(
    store: HyperGraphStore,
    vector_store: Any,
    embedding_service: Any,
    query: str,
    silo_id: str,
    options: RecallOptions | None = None,
) -> RecallResult:
    """RECALL: Query transaction with epistemic-aware retrieval.

    Per brain-transactions-pseudocode.md RECALL:
    1. Vector search with over-fetch
    2. Apply filters (state, temporal, layer, confidence)
    3. Score by layer semantics
    4. Graph traversal (if depth > 0)
    5. Lazy synthesis (if enabled)
    """
    from context_service.db import queries as q
    from context_service.sage.transactions import synthesize as tx4_synthesize

    start_time = datetime.now(UTC)

    if options is None:
        options = RecallOptions()

    # Validation
    if not silo_id:
        raise ValueError("silo_id is required")
    if not query or not query.strip():
        raise ValueError("query is required")

    # 1. Vector search with over-fetch
    query_embedding = await embedding_service.embed_query(query)
    over_fetch_k = options.top_k * 3
    candidates = await vector_store.search(
        collection=silo_id,
        vector=query_embedding,
        top_k=over_fetch_k,
    )

    # 2. Apply filters
    filtered: list[tuple[dict[str, Any], float]] = []

    for candidate in candidates:
        node_id = candidate.get("id")
        similarity = candidate.get("score", 0.0)

        # Fetch full node
        node_results = await store.execute_query(
            q.GET_NODE_FOR_RECALL,
            {"node_id": node_id, "silo_id": silo_id},
        )
        if not node_results:
            continue

        node = node_results[0]

        # State filter
        state = node.get("state")
        if state in (NodeState.TOMBSTONED.value, NodeState.DELETED.value):
            continue
        if state == NodeState.SUPERSEDED.value and not options.include_superseded:
            continue

        # Temporal filter (as_of)
        if options.as_of is not None:
            created_at = node.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                if created_at > options.as_of:
                    continue

            valid_to = node.get("valid_to")
            if valid_to:
                if isinstance(valid_to, str):
                    valid_to = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
                if valid_to < options.as_of:
                    continue

        # Layer filter
        if options.layers is not None:
            node_layer = node.get("layer")
            if node_layer not in [layer.value for layer in options.layers]:
                continue

        # Confidence filter
        confidence = float(node.get("confidence", 0.0))
        if confidence < options.min_confidence:
            continue

        filtered.append((node, float(similarity)))

    # 3. Score by layer semantics
    scored: list[tuple[dict[str, Any], float]] = []
    for node, similarity in filtered:
        # Heat from reactions (reserved for future implementation)
        heat = 0.0
        score = compute_recall_score(node, similarity, heat)
        scored.append((node, score))

    # Sort by score descending, take top_k
    scored.sort(key=lambda x: x[1], reverse=True)
    top_results = scored[: options.top_k]

    # 4. Build results with optional graph traversal
    results: list[RecallResultItem] = []
    for node, score in top_results:
        related: list[RelatedNode] = []
        if options.depth > 0:
            related = await traverse_graph(
                store=store,
                node_id=node.get("id"),
                silo_id=silo_id,
                max_depth=options.depth,
            )

        node_created_at = node.get("created_at")
        if isinstance(node_created_at, str):
            node_created_at = datetime.fromisoformat(node_created_at.replace("Z", "+00:00"))
        elif node_created_at is None:
            node_created_at = datetime.now(UTC)

        results.append(
            RecallResultItem(
                node_id=node.get("id", str(uuid.uuid4())),
                content=node.get("content", ""),
                layer=node.get("layer", Layer.MEMORY.value),
                score=score,
                confidence=float(node.get("confidence", 0.0)),
                created_at=node_created_at,
                properties=node.get("properties", {}),
                related=related,
                synthesized=False,
            )
        )

    # 5. Lazy synthesis (if enabled)
    synthesis_pending = False
    if options.include_synthesis and results:
        node_ids = [r.node_id for r in results]

        cluster_results = await store.execute_query(
            q.GET_CLUSTERS_FOR_NODES,
            {"silo_id": silo_id, "node_ids": node_ids},
        )

        for cluster in cluster_results:
            cluster_id = cluster.get("cluster_id")
            cluster_state = cluster.get("state")
            current_belief_id = cluster.get("current_belief_id")

            if cluster_state in (ClusterState.READY.value, ClusterState.STALE.value):
                if current_belief_id is None:
                    try:
                        belief_result, _ = await tx4_synthesize(
                            store=store,
                            cluster_id=cluster_id,
                            silo_id=silo_id,
                            llm=None,  # type: ignore[arg-type]
                            _embedder=embedding_service,
                            mode="sync",
                        )
                        if belief_result and belief_result.belief_id:
                            results.append(
                                RecallResultItem(
                                    node_id=str(belief_result.belief_id),
                                    content="",
                                    layer=Layer.WISDOM.value,
                                    score=1.0,
                                    confidence=belief_result.confidence or 0.0,
                                    created_at=datetime.now(UTC),
                                    properties={},
                                    related=[],
                                    synthesized=True,
                                )
                            )
                    except Exception:
                        logger.warning(
                            "lazy_synthesis_failed",
                            cluster_id=cluster_id,
                        )
                        synthesis_pending = True

    elapsed_ms = (datetime.now(UTC) - start_time).total_seconds() * 1000

    return RecallResult(
        results=results,
        total_candidates=len(candidates),
        synthesis_pending=synthesis_pending,
        query_time_ms=elapsed_ms,
    )


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
