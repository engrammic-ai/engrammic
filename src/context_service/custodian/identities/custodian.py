from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class ContradictionResult(BaseModel):
    has_contradiction: bool
    supersedes_ids: list[str] = []
    reason: str | None = None


SIMILAR_FACTS_QUERY = """
MATCH (new:Fact {id: $fact_id, silo_id: $silo_id})
MATCH (existing:Fact {silo_id: $silo_id})
WHERE existing.id <> new.id
  AND existing.subject = new.subject
  AND existing.predicate = new.predicate
RETURN existing.id AS fact_id, existing.content AS content
LIMIT 10
"""

WRITE_SUPERSEDES_QUERY = """
MATCH (new:Fact {id: $new_id, silo_id: $silo_id})
MATCH (old:Fact {id: $old_id, silo_id: $silo_id})
MERGE (new)-[:SUPERSEDES {reason: $reason, created_at: datetime()}]->(old)
"""


@dataclass
class CustodianIdentity:
    """Contradiction detection and supersession (T2)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-flash"

    async def check_contradiction(self, fact_id: str) -> ContradictionResult:
        """Check if a new fact contradicts existing facts."""
        similar = await self.store.execute_query(
            SIMILAR_FACTS_QUERY,
            {"fact_id": fact_id, "silo_id": self.silo_id},
        )

        if not similar:
            return ContradictionResult(has_contradiction=False)

        # TODO: Use LLM agent to determine actual contradiction
        # For now, just flag potential conflicts
        return ContradictionResult(
            has_contradiction=False,
            supersedes_ids=[],
            reason=None,
        )

    async def write_supersession(self, new_id: str, old_id: str, reason: str) -> None:
        """Write SUPERSEDES edge between facts."""
        await self.store.execute_write(
            WRITE_SUPERSEDES_QUERY,
            {"new_id": new_id, "old_id": old_id, "silo_id": self.silo_id, "reason": reason},
        )
        logger.info(
            "custodian.supersession_written",
            new_id=new_id,
            old_id=old_id,
            reason=reason,
            identity="custodian",
        )
