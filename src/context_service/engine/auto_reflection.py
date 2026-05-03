"""System-generated MetaObservation nodes for significant epistemic events.

Auto-reflections are written inline using template-based content (no LLM call).
They use ``agent_id = "system"`` and carry ``auto_generated = True`` to
distinguish them from agent-initiated reflections created via ``context_reflect``.

Public API
----------
create_auto_reflection(store, observation_type, content, about_node_ids, silo_id)
    -> str | None
    Write a :MetaObservation node with ABOUT edges and return its id.
    Returns None if the write fails non-fatally (logged, never re-raised).

make_supersession_content(old_content, new_content, reason) -> str
make_revision_content(subject, magnitude_pct) -> str
    Convenience template builders used by hook sites.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = structlog.get_logger(__name__)

_SYSTEM_AGENT_ID = "system"

# Cypher: create a MetaObservation node and wire ABOUT edges in one statement.
_CREATE_AUTO_REFLECTION = """
MERGE (obs:MetaObservation {id: $obs_id, silo_id: $silo_id})
ON CREATE SET
    obs.content = $content,
    obs.observation_type = $observation_type,
    obs.confidence = $confidence,
    obs.agent_id = $agent_id,
    obs.auto_generated = true,
    obs.created_at = $created_at
WITH obs
UNWIND $about_node_ids AS target_id
MATCH (target {id: target_id, silo_id: $silo_id})
MERGE (obs)-[:ABOUT]->(target)
"""


def make_supersession_content(old_content: str, new_content: str, reason: str) -> str:
    """Build the observation text for a fact supersession event."""
    old_snippet = old_content[:80].replace("'", "`")
    new_snippet = new_content[:80].replace("'", "`")
    return f"Fact '{old_snippet}' was superseded by '{new_snippet}' due to {reason}"


def make_revision_content(subject: str, magnitude_pct: float) -> str:
    """Build the observation text for a belief revision event."""
    subj_snippet = subject[:80].replace("'", "`")
    return f"Belief about '{subj_snippet}' was revised due to evidence shift ({magnitude_pct:.1f}%)"


async def create_auto_reflection(
    store: HyperGraphStore,
    observation_type: str,
    content: str,
    about_node_ids: list[str],
    silo_id: str,
    *,
    confidence: float = 0.9,
) -> str | None:
    """Create a system-generated MetaObservation node.

    Parameters
    ----------
    store:
        HyperGraphStore implementation.
    observation_type:
        One of the ObservationType values (e.g. ``"belief_change"``).
    content:
        Human-readable description of the event (template-built by callers).
    about_node_ids:
        IDs of graph nodes this observation concerns. Nodes that do not exist
        in the silo are silently skipped by the MATCH clause.
    silo_id:
        Silo scope for the new MetaObservation and ABOUT edge targets.
    confidence:
        Assigned confidence for the auto-generated observation. Default 0.9 —
        auto-reflections are deterministic so high confidence is appropriate.

    Returns
    -------
    str | None
        The new MetaObservation's id string, or None on a non-fatal write error.
    """
    obs_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()

    try:
        await store.execute_write(
            _CREATE_AUTO_REFLECTION,
            {
                "obs_id": obs_id,
                "silo_id": silo_id,
                "content": content,
                "observation_type": observation_type,
                "confidence": confidence,
                "agent_id": _SYSTEM_AGENT_ID,
                "created_at": now,
                "about_node_ids": about_node_ids,
            },
        )
    except Exception as exc:
        logger.warning(
            "auto_reflection_write_failed",
            observation_type=observation_type,
            silo_id=silo_id,
            about_node_ids=about_node_ids,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return None

    logger.debug(
        "auto_reflection_created",
        obs_id=obs_id,
        observation_type=observation_type,
        silo_id=silo_id,
        about_node_ids=about_node_ids,
    )
    return obs_id
