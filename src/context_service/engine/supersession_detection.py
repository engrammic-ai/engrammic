"""Write-time supersession candidate detection.

Tiered approach to detecting when a new write should supersede existing content:

Tier 0: Session recall cache (free, ~1ms)
    If agent recalled node X in this session and now writes about same subject,
    strong signal this is an update.

Tier 1: SPO index lookup (cheap, ~5ms)
    Same (subject, predicate) + different object + same agent = update pattern.

Tier 2: Semantic similarity (existing, ~50ms)
    Reuses contradiction_candidates infrastructure, filtered to same-agent.

Auto-supersede thresholds:
- Recalled in session + SPO.subject match → auto
- SPO (S,P) match + same agent + same session → auto
- SPO (S,P) match + same agent + <5min → auto
- Everything else → return candidates for agent decision

# ponytail: 1:N supersession supported at edge level but pointer optimization
# (tail_id/head_id) only tracks first chain. Upgrade to DAG traversal if 1:N
# becomes common; current approach trades O(1) for simplicity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import structlog

from context_service.config.settings import get_settings

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

# Time window for auto-supersession without session match
AUTO_SUPERSEDE_WINDOW = timedelta(minutes=5)


@dataclass
class SupersessionCandidate:
    """A node that might be superseded by the new write."""

    node_id: str
    subject: str | None
    predicate: str | None
    object: str | None
    confidence: float  # 0-1, higher = more likely this is an update
    reason: str  # "session_recall", "spo_match", "semantic_similarity"
    auto_supersede: bool  # True if confidence high enough to auto-supersede


@dataclass
class SupersessionDetectionResult:
    """Result of supersession detection at write time."""

    candidates: list[SupersessionCandidate]
    auto_supersede_id: str | None  # If set, auto-supersede this node
    detection_ms: float


# Tier 0: Check if any recalled nodes in this session match the new content's subject
_SESSION_RECALLED_BY_SUBJECT = """
MATCH (s:Session {id: $session_id, silo_id: $silo_id})-[:ACCESSED_BY]->(n)
WHERE n.silo_id = $silo_id
  AND n.subject IS NOT NULL
  AND toLower(n.subject) = toLower($subject)
  AND n.agent_id = $agent_id
RETURN n.id AS node_id, n.subject AS subject, n.predicate AS predicate,
       n.object AS object, n.created_at AS created_at
ORDER BY n.created_at DESC
LIMIT 5
"""

# Tier 1: Find nodes with same (subject, predicate) from same agent
_SPO_MATCH_SAME_AGENT = """
MATCH (n)
WHERE (n:Claim OR n:Fact OR n:Memory)
  AND n.silo_id = $silo_id
  AND n.agent_id = $agent_id
  AND n.subject IS NOT NULL
  AND toLower(n.subject) = toLower($subject)
  AND n.predicate IS NOT NULL
  AND toLower(n.predicate) = toLower($predicate)
  AND n.id <> $exclude_id
  AND n.valid_to IS NULL
RETURN n.id AS node_id, n.subject AS subject, n.predicate AS predicate,
       n.object AS object, n.created_at AS created_at, n.session_id AS session_id
ORDER BY n.created_at DESC
LIMIT 10
"""

# Tier 1 fallback: Subject match only (when predicate not available)
_SUBJECT_MATCH_SAME_AGENT = """
MATCH (n)
WHERE (n:Claim OR n:Fact OR n:Memory)
  AND n.silo_id = $silo_id
  AND n.agent_id = $agent_id
  AND n.subject IS NOT NULL
  AND toLower(n.subject) = toLower($subject)
  AND n.id <> $exclude_id
  AND n.valid_to IS NULL
RETURN n.id AS node_id, n.subject AS subject, n.predicate AS predicate,
       n.object AS object, n.created_at AS created_at, n.session_id AS session_id
ORDER BY n.created_at DESC
LIMIT 10
"""


async def detect_supersession_candidates(
    store: HyperGraphStore,
    silo_id: str,
    node_id: str,
    agent_id: str,
    session_id: str | None,
    subject: str | None,
    predicate: str | None,
    obj: str | None,
    embedding: list[float] | None = None,
    qdrant_client: Any | None = None,
) -> SupersessionDetectionResult:
    """Detect nodes that the new write might be superseding.

    Runs tiers in order, returns as soon as high-confidence match found.

    Args:
        store: Graph store for queries
        silo_id: Tenant silo
        node_id: ID of the newly written node (to exclude from results)
        agent_id: Agent writing the new content
        session_id: Current session (for recall tracking)
        subject: SPO subject of new content (if available)
        predicate: SPO predicate of new content (if available)
        obj: SPO object of new content (if available)
        embedding: Embedding vector (for Tier 2 semantic similarity)
        qdrant_client: Qdrant client (for Tier 2)

    Returns:
        SupersessionDetectionResult with candidates and optional auto_supersede_id
    """
    start = datetime.now(UTC)
    candidates: list[SupersessionCandidate] = []
    auto_supersede_id: str | None = None
    now = datetime.now(UTC)

    # Tier 0: Session recall check (only if we have session and subject)
    if session_id and subject:
        try:
            recalled = await store.execute_query(
                _SESSION_RECALLED_BY_SUBJECT,
                {
                    "session_id": session_id,
                    "silo_id": silo_id,
                    "subject": subject,
                    "agent_id": agent_id,
                },
            )
            for row in recalled:
                candidate = SupersessionCandidate(
                    node_id=row["node_id"],
                    subject=row.get("subject"),
                    predicate=row.get("predicate"),
                    object=row.get("object"),
                    confidence=0.95,
                    reason="session_recall",
                    auto_supersede=True,
                )
                candidates.append(candidate)
                # First recalled match with subject = auto-supersede
                if auto_supersede_id is None:
                    auto_supersede_id = row["node_id"]
                    logger.info(
                        "supersession_auto_detected",
                        reason="session_recall",
                        new_id=node_id,
                        supersedes_id=auto_supersede_id,
                    )
        except Exception as exc:
            logger.debug("tier0_session_recall_failed", error=str(exc))

    # Tier 1: SPO match (only if we have subject)
    if subject and not auto_supersede_id:
        try:
            if predicate:
                # Full (S,P) match
                spo_matches = await store.execute_query(
                    _SPO_MATCH_SAME_AGENT,
                    {
                        "silo_id": silo_id,
                        "agent_id": agent_id,
                        "subject": subject,
                        "predicate": predicate,
                        "exclude_id": node_id,
                    },
                )
            else:
                # Subject-only match (weaker signal)
                spo_matches = await store.execute_query(
                    _SUBJECT_MATCH_SAME_AGENT,
                    {
                        "silo_id": silo_id,
                        "agent_id": agent_id,
                        "subject": subject,
                        "exclude_id": node_id,
                    },
                )

            for row in spo_matches:
                # Skip if already in candidates from Tier 0
                if any(c.node_id == row["node_id"] for c in candidates):
                    continue

                # Determine confidence and auto-supersede eligibility
                same_session = row.get("session_id") == session_id
                created_at_str = row.get("created_at")
                recent = False
                if created_at_str:
                    try:
                        created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                        recent = (now - created_at) < AUTO_SUPERSEDE_WINDOW
                    except (ValueError, TypeError):
                        pass

                has_predicate_match = bool(predicate and row.get("predicate"))
                different_object = bool(obj and row.get("object") and obj != row.get("object"))

                # Auto-supersede if: same (S,P), different O, and (same session OR recent)
                should_auto = bool(
                    has_predicate_match and different_object and (same_session or recent)
                )

                confidence = 0.9 if has_predicate_match else 0.7
                if same_session:
                    confidence += 0.05
                if recent:
                    confidence += 0.03

                candidate = SupersessionCandidate(
                    node_id=row["node_id"],
                    subject=row.get("subject"),
                    predicate=row.get("predicate"),
                    object=row.get("object"),
                    confidence=min(confidence, 1.0),
                    reason="spo_match" if has_predicate_match else "subject_match",
                    auto_supersede=should_auto,
                )
                candidates.append(candidate)

                if should_auto and auto_supersede_id is None:
                    auto_supersede_id = row["node_id"]
                    logger.info(
                        "supersession_auto_detected",
                        reason="spo_match",
                        new_id=node_id,
                        supersedes_id=auto_supersede_id,
                        same_session=same_session,
                        recent=recent,
                    )
        except Exception as exc:
            logger.debug("tier1_spo_match_failed", error=str(exc))

    # Tier 2: Semantic similarity (reuse contradiction infrastructure)
    # Only if no auto-supersede found and embedding available
    settings = get_settings()
    if (
        not auto_supersede_id
        and embedding
        and qdrant_client
        and settings.supersession_detection.semantic_fallback_enabled
    ):
        try:
            from context_service.engine.contradiction import check_contradiction_candidates

            similar_ids = await check_contradiction_candidates(
                store=store,
                silo_id=silo_id,
                node_id=node_id,
                embedding=embedding,
                qdrant_client=qdrant_client,
                threshold=settings.supersession_detection.similarity_threshold,
                max_candidates=10,
            )

            # Filter to same-agent (contradiction check includes all agents)
            for similar_id in similar_ids:
                if any(c.node_id == similar_id for c in candidates):
                    continue

                # Fetch node to check agent
                try:
                    rows = await store.execute_query(
                        "MATCH (n {id: $id, silo_id: $silo_id}) RETURN n.agent_id AS agent_id, "
                        "n.subject AS subject, n.predicate AS predicate, n.object AS object",
                        {"id": similar_id, "silo_id": silo_id},
                    )
                    if rows and rows[0].get("agent_id") == agent_id:
                        candidates.append(
                            SupersessionCandidate(
                                node_id=similar_id,
                                subject=rows[0].get("subject"),
                                predicate=rows[0].get("predicate"),
                                object=rows[0].get("object"),
                                confidence=0.5,  # Lower confidence - semantic only
                                reason="semantic_similarity",
                                auto_supersede=False,  # Never auto on semantic alone
                            )
                        )
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("tier2_semantic_failed", error=str(exc))

    elapsed_ms = (datetime.now(UTC) - start).total_seconds() * 1000

    return SupersessionDetectionResult(
        candidates=candidates,
        auto_supersede_id=auto_supersede_id,
        detection_ms=elapsed_ms,
    )


def format_candidates_for_response(result: SupersessionDetectionResult) -> dict[str, Any]:
    """Format detection result for MCP tool response."""
    if not result.candidates:
        return {}

    response: dict[str, Any] = {}

    if result.auto_supersede_id:
        response["auto_superseded"] = result.auto_supersede_id

    # Group by confidence tier
    high_confidence = [c for c in result.candidates if c.confidence >= 0.8]
    medium_confidence = [c for c in result.candidates if 0.5 <= c.confidence < 0.8]

    if high_confidence:
        response["likely_updates"] = [
            {
                "id": c.node_id,
                "subject": c.subject,
                "predicate": c.predicate,
                "object": c.object,
                "reason": c.reason,
            }
            for c in high_confidence
            if c.node_id != result.auto_supersede_id  # Don't duplicate auto
        ]

    if medium_confidence:
        response["possible_updates"] = [
            {"id": c.node_id, "reason": c.reason} for c in medium_confidence
        ]

    return response
