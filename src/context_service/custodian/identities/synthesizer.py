from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)

SYNTHESIS_CANDIDATES_QUERY = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE NOT exists((c)<-[:COVERS]-(:Belief))
WITH c, size((c)-[:CONTAINS]->()) AS fact_count
WHERE fact_count >= $min_facts
RETURN c.id AS cluster_id, fact_count, c.confidence AS confidence
ORDER BY fact_count DESC
LIMIT 50
"""


@dataclass
class SynthesizerIdentity:
    """Weak synthesis, ProposedBelief creation, revision (T3/T4/T10)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-pro"
    min_facts_for_synthesis: int = 3

    async def find_synthesis_candidates(self) -> list[dict]:
        """Find clusters ready for synthesis."""
        rows = await self.store.execute_query(
            SYNTHESIS_CANDIDATES_QUERY,
            {"silo_id": self.silo_id, "min_facts": self.min_facts_for_synthesis},
        )
        return list(rows)

    async def run_synthesis(self) -> dict:
        """Run synthesis for all candidates in silo."""
        candidates = await self.find_synthesis_candidates()

        if not candidates:
            return {"candidates": 0, "created": 0, "silo_id": self.silo_id}

        # TODO: Actually create ProposedBeliefs via LLM
        # For now, just log candidates found
        logger.info(
            "synthesizer.candidates_found",
            silo_id=self.silo_id,
            candidates=len(candidates),
            identity="synthesizer",
        )

        return {"candidates": len(candidates), "created": 0, "silo_id": self.silo_id}
