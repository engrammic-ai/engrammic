"""Write-time cross-agent conflict detection.

When an agent writes a node that semantically contradicts another agent's
existing content, this module detects it and creates a CONTRADICTS edge.

Detection flow:
1. After write, search Qdrant for similar nodes from OTHER agents.
2. For each candidate, run a two-stage contradiction check:
   a. Structural SPO check: same subject + same predicate + different object.
   b. If no structural conflict, fall back to embedding cosine similarity +
      subject match (catches semantic contradictions without full SPO).
3. If either check fires, create a CONTRADICTS edge with resolution metadata.
4. Return the list of created edge IDs (fire-and-forget acceptable).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings

if TYPE_CHECKING:
    from context_service.auth.identity import IdentityContext
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

_CREATE_CONTRADICTS_EDGE = """
MATCH (a {id: $source_id, silo_id: $silo_id})
MATCH (b {id: $target_id, silo_id: $silo_id})
MERGE (a)-[r:CONTRADICTS {id: $edge_id}]->(b)
ON CREATE SET
    r.detected_by = $detected_by,
    r.resolution_status = $resolution_status,
    r.detected_at = $detected_at,
    r.resolved_by = null,
    r.resolved_at = null
RETURN r.id AS edge_id
"""

_GET_NODE_PROPERTIES = """
MATCH (n {id: $node_id, silo_id: $silo_id})
RETURN n.id AS id, n.embedding AS embedding, labels(n) AS labels,
       n.subject AS subject, n.spo AS spo
"""


def has_structural_spo_conflict(
    node_a_props: dict[str, Any],
    node_b_props: dict[str, Any],
) -> bool:
    """Check if two nodes structurally contradict each other via SPO.

    Two nodes structurally contradict when they share the same subject and
    predicate but assert different objects -- i.e., they answer the same
    question differently.

    Example:
        Claim A: subject="API", predicate="uses", object="OAuth2"
        Claim B: subject="API", predicate="uses", object="API keys"
        -> structural conflict: same question, different answer.

    Args:
        node_a_props: Properties of the first node (must include spo dict).
        node_b_props: Properties of the second node (must include spo dict).

    Returns:
        True if same subject + same predicate but different object.
    """
    spo_a = node_a_props.get("spo")
    spo_b = node_b_props.get("spo")

    if not spo_a or not spo_b:
        return False

    subject_a = (spo_a.get("subject") or "").lower().strip()
    subject_b = (spo_b.get("subject") or "").lower().strip()
    predicate_a = (spo_a.get("predicate") or "").lower().strip()
    predicate_b = (spo_b.get("predicate") or "").lower().strip()
    object_a = (spo_a.get("object") or "").lower().strip()
    object_b = (spo_b.get("object") or "").lower().strip()

    if not subject_a or not subject_b or not predicate_a or not predicate_b:
        return False

    return subject_a == subject_b and predicate_a == predicate_b and object_a != object_b


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot: float = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a: float = sum(x * x for x in a) ** 0.5
    norm_b: float = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def is_same_subject(
    node_a_props: dict[str, Any],
    node_b_props: dict[str, Any],
) -> bool:
    """Check if two nodes are about the same subject.

    Prefers SPO subject comparison when available. Falls back to embedding
    cosine similarity + label match.

    Args:
        node_a_props: Properties of the first node (must include embedding, labels).
        node_b_props: Properties of the second node (must include embedding, labels).

    Returns:
        True if the nodes appear to be about the same subject.
    """
    spo_a = node_a_props.get("spo")
    spo_b = node_b_props.get("spo")

    if spo_a and spo_b:
        subject_a = (spo_a.get("subject") or "").lower().strip()
        subject_b = (spo_b.get("subject") or "").lower().strip()
        if subject_a and subject_b:
            return subject_a == subject_b
        return False

    emb_a = node_a_props.get("embedding") or []
    emb_b = node_b_props.get("embedding") or []
    labels_a = set(node_a_props.get("labels") or [])
    labels_b = set(node_b_props.get("labels") or [])

    same_label = bool(labels_a & labels_b)
    if not same_label:
        return False

    similarity = _cosine(emb_a, emb_b)
    return similarity > 0.85


async def create_contradicts_edge(
    store: HyperGraphStore,
    source_id: str,
    target_id: str,
    silo_id: str,
) -> str | None:
    """Create a CONTRADICTS edge with resolution metadata.

    Args:
        store: Graph store for writing.
        source_id: New node ID (source of contradiction).
        target_id: Existing conflicting node ID.
        silo_id: Tenant silo.

    Returns:
        The edge ID if created, None on failure.
    """
    edge_id = str(uuid.uuid4())
    detected_at = datetime.now(UTC).isoformat()

    try:
        result = await store.execute_write(
            _CREATE_CONTRADICTS_EDGE,
            {
                "edge_id": edge_id,
                "source_id": source_id,
                "target_id": target_id,
                "silo_id": silo_id,
                "detected_by": "system",
                "resolution_status": "unresolved",
                "detected_at": detected_at,
            },
        )
        if result:
            logger.info(
                "contradicts_edge_created",
                edge_id=edge_id,
                source_id=source_id,
                target_id=target_id,
                silo_id=silo_id,
            )
            return edge_id
        return None
    except Exception as exc:
        logger.warning(
            "contradicts_edge_creation_failed",
            source_id=source_id,
            target_id=target_id,
            error=str(exc),
        )
        return None


async def detect_conflicts(
    store: HyperGraphStore,
    node_id: str,
    node_embedding: list[float],
    ctx: IdentityContext,
    qdrant_client: Any | None = None,
) -> list[str]:
    """Detect cross-agent conflicts for a newly written node.

    Searches for similar nodes from OTHER agents and creates CONTRADICTS edges
    for those that share the same subject.

    Args:
        store: Graph store for reading node props and writing edges.
        node_id: ID of the newly written node.
        node_embedding: Embedding vector of the new node.
        ctx: Identity context of the writing agent.
        qdrant_client: Raw Qdrant client for vector search.

    Returns:
        List of created CONTRADICTS edge IDs.
    """
    settings = get_settings()
    if not settings.conflict_detection.enabled:
        return []

    if not node_embedding or qdrant_client is None:
        return []

    collection_name = f"ctx_{ctx.tenant_id}"
    threshold = settings.conflict_detection.similarity_threshold

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must_not: list[Any] = [
            FieldCondition(key="node_id", match=MatchValue(value=node_id)),
        ]
        if settings.conflict_detection.check_other_agents_only:
            must_not.append(
                FieldCondition(key="agent_id", match=MatchValue(value=ctx.agent_id)),
            )

        search_result = await qdrant_client.search(
            collection_name=collection_name,
            query_vector=node_embedding,
            limit=10,
            score_threshold=threshold,
            query_filter=Filter(must_not=must_not),
        )
    except Exception as exc:
        logger.debug("conflict_detection_search_failed", error=str(exc), node_id=node_id)
        return []

    if not search_result:
        return []

    # Fetch new node's properties for subject comparison
    try:
        new_node_rows = await store.execute_query(
            _GET_NODE_PROPERTIES,
            {"node_id": node_id, "silo_id": ctx.tenant_id},
        )
        new_node_props: dict[str, Any] = new_node_rows[0] if new_node_rows else {}
        new_node_props["embedding"] = node_embedding
    except Exception as exc:
        logger.debug("conflict_detection_node_fetch_failed", error=str(exc), node_id=node_id)
        return []

    edge_ids: list[str] = []
    for hit in search_result:
        if not hit.payload:
            continue
        candidate_id = hit.payload.get("node_id")
        if not candidate_id or candidate_id == node_id:
            continue

        try:
            candidate_rows = await store.execute_query(
                _GET_NODE_PROPERTIES,
                {"node_id": candidate_id, "silo_id": ctx.tenant_id},
            )
            if not candidate_rows:
                continue
            candidate_props = candidate_rows[0]
            candidate_emb = hit.payload.get("embedding") or candidate_props.get("embedding") or []
            candidate_props["embedding"] = candidate_emb
        except Exception as exc:
            logger.debug(
                "conflict_detection_candidate_fetch_failed",
                error=str(exc),
                candidate_id=candidate_id,
            )
            continue

        # Structural SPO check: same subject + predicate, different object.
        # Run this before the embedding fallback -- it is cheaper and catches
        # contradictions that are not semantically similar.
        structural_conflict = has_structural_spo_conflict(new_node_props, candidate_props)
        if structural_conflict:
            logger.debug(
                "structural_spo_conflict_detected",
                node_id=node_id,
                candidate_id=candidate_id,
            )
        else:
            same_subject = await is_same_subject(new_node_props, candidate_props)
            if not same_subject:
                continue

        edge_id = await create_contradicts_edge(
            store=store,
            source_id=node_id,
            target_id=candidate_id,
            silo_id=ctx.tenant_id,
        )
        if edge_id:
            edge_ids.append(edge_id)

    return edge_ids
