from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_ai import Agent

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class SynthesisResult(BaseModel):
    """LLM output for belief synthesis."""

    belief_statement: str
    confidence: float
    supporting_fact_ids: list[str]
    reasoning: str


SYNTHESIS_SYSTEM_PROMPT = """You synthesize related facts into belief statements.

Given a cluster of related facts:
1. Identify the common theme or assertion
2. Formulate a single belief statement that captures the synthesis
3. Rate confidence based on fact agreement (0-1)
4. List which fact IDs directly support this belief

A belief should be:
- More general than individual facts
- Supported by multiple facts
- Stated as a confident assertion

Return ONLY fact IDs that appear in the input."""


def _build_synthesis_agent(model: str) -> Agent[None, SynthesisResult]:
    return Agent(
        model=model,
        output_type=SynthesisResult,
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
    )


SYNTHESIS_CANDIDATES_QUERY = """
MATCH (c:Cluster {silo_id: $silo_id})
WHERE NOT exists((c)<-[:COVERS]-(:Belief))
  AND NOT exists((c)<-[:COVERS]-(:ProposedBelief {status: 'pending'}))
WITH c, size((c)-[:CONTAINS]->()) AS fact_count
WHERE fact_count >= $min_facts
RETURN c.id AS cluster_id, fact_count, c.confidence AS confidence
ORDER BY fact_count DESC
LIMIT 50
"""

CLUSTER_FACTS_QUERY = """
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})-[:CONTAINS]->(f:Fact)
RETURN f.id AS id, f.content AS content
LIMIT $max_facts
"""

CREATE_PROPOSED_BELIEF_QUERY = """
CREATE (p:ProposedBelief {
    id: $id,
    silo_id: $silo_id,
    content: $content,
    confidence: $confidence,
    created_at: $created_at,
    status: 'pending'
})
WITH p
MATCH (c:Cluster {id: $cluster_id, silo_id: $silo_id})
MERGE (p)-[:COVERS]->(c)
WITH p
UNWIND $fact_ids AS fid
MATCH (f:Fact {id: fid, silo_id: $silo_id})
MERGE (p)-[:DERIVED_FROM]->(f)
"""


@dataclass
class SynthesizerIdentity:
    """Weak synthesis, ProposedBelief creation, revision (T3/T4/T10)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-pro"
    min_facts_for_synthesis: int = 3
    max_facts_per_synthesis: int = 10
    timeout_seconds: float = 60.0
    proposal_threshold: float = 0.6

    async def find_synthesis_candidates(self) -> list[dict[str, object]]:
        """Find clusters ready for synthesis."""
        rows = await self.store.execute_query(
            SYNTHESIS_CANDIDATES_QUERY,
            {"silo_id": self.silo_id, "min_facts": self.min_facts_for_synthesis},
        )
        return list(rows)

    async def run_synthesis(self) -> dict[str, object]:
        """Run synthesis for all candidates in silo."""
        candidates = await self.find_synthesis_candidates()

        if not candidates:
            return {"candidates": 0, "created": 0, "silo_id": self.silo_id}

        logger.info(
            "synthesizer.candidates_found",
            silo_id=self.silo_id,
            candidates=len(candidates),
            identity="synthesizer",
        )

        agent = _build_synthesis_agent(self.model)
        created: list[str] = []

        for candidate in candidates:
            cluster_id = candidate["cluster_id"]
            facts = await self.store.execute_query(
                CLUSTER_FACTS_QUERY,
                {
                    "cluster_id": cluster_id,
                    "silo_id": self.silo_id,
                    "max_facts": self.max_facts_per_synthesis,
                },
            )

            if len(facts) < self.min_facts_for_synthesis:
                continue

            prompt = f"""FACTS IN CLUSTER:
{chr(10).join(f"- [{f['id']}]: {f['content']}" for f in facts)}

Synthesize into a belief statement."""

            try:
                result = await asyncio.wait_for(
                    agent.run(prompt),
                    timeout=self.timeout_seconds,
                )
            except TimeoutError:
                logger.warning("synthesizer.llm_timeout", cluster_id=cluster_id)
                continue
            except Exception as e:
                logger.warning("synthesizer.llm_error", cluster_id=cluster_id, error=str(e))
                continue

            if result.output.confidence < self.proposal_threshold:
                continue

            valid_ids = {f["id"] for f in facts}
            supporting = [fid for fid in result.output.supporting_fact_ids if fid in valid_ids]

            if not supporting:
                continue

            proposal_id = await self._create_proposed_belief(
                content=result.output.belief_statement,
                confidence=result.output.confidence,
                supporting_facts=supporting,
                cluster_id=str(cluster_id),
            )
            if proposal_id:
                created.append(proposal_id)

        return {"candidates": len(candidates), "created": len(created), "silo_id": self.silo_id}

    async def _create_proposed_belief(
        self,
        content: str,
        confidence: float,
        supporting_facts: list[str],
        cluster_id: str,
    ) -> str | None:
        """Create ProposedBelief node with COVERS edge to cluster."""
        proposal_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        try:
            await self.store.execute_write(
                CREATE_PROPOSED_BELIEF_QUERY,
                {
                    "id": proposal_id,
                    "silo_id": self.silo_id,
                    "content": content,
                    "confidence": confidence,
                    "created_at": now,
                    "cluster_id": cluster_id,
                    "fact_ids": supporting_facts,
                },
            )
        except Exception as e:
            logger.error("synthesizer.create_proposed_belief_failed", error=str(e))
            return None

        logger.info(
            "synthesizer.proposed_belief_created",
            proposal_id=proposal_id,
            cluster_id=cluster_id,
            confidence=confidence,
            identity="synthesizer",
        )

        return proposal_id
