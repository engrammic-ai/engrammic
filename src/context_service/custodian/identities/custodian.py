from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel
from pydantic_ai import Agent

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings
from context_service.telemetry.metrics import record_supersession_used

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class ContradictionResult(BaseModel):
    has_contradiction: bool
    supersedes_ids: list[str] = []
    reason: str | None = None


class ContradictionAnalysis(BaseModel):
    """LLM output for contradiction check."""

    has_contradiction: bool
    supersedes: list[str] = []
    reasoning: str
    confidence: float


CONTRADICTION_SYSTEM_PROMPT = """You analyze facts for logical contradiction.

Given a NEW fact and EXISTING facts with the same subject/predicate:
1. Determine if the new fact contradicts any existing facts
2. If so, identify which existing facts are superseded (by their IDs)
3. Provide brief reasoning
4. Rate your confidence (0-1)

A contradiction exists when facts cannot both be true simultaneously.
Temporal updates (newer info replacing older) count as supersession.

Return ONLY facts that are truly contradicted or superseded."""


def _build_contradiction_agent(model: str) -> Agent[None, ContradictionAnalysis]:
    return Agent(
        model=model,
        output_type=ContradictionAnalysis,
        system_prompt=CONTRADICTION_SYSTEM_PROMPT,
    )


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


FETCH_FACT_QUERY = """
MATCH (f:Fact {id: $id, silo_id: $silo_id})
RETURN f.content AS content
"""


@dataclass
class CustodianIdentity:
    """Contradiction detection and supersession (T2)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-flash"
    timeout_seconds: float = 30.0
    min_confidence: float = 0.7

    async def check_contradiction(self, fact_id: str) -> ContradictionResult:
        """Check if a new fact contradicts existing facts."""
        similar = await self.store.execute_query(
            SIMILAR_FACTS_QUERY,
            {"fact_id": fact_id, "silo_id": self.silo_id},
        )

        if not similar:
            return ContradictionResult(has_contradiction=False)

        new_fact = await self.store.execute_query(
            FETCH_FACT_QUERY,
            {"id": fact_id, "silo_id": self.silo_id},
        )

        if not new_fact:
            return ContradictionResult(has_contradiction=False)

        prompt = f"""NEW FACT: {new_fact[0]["content"]}

EXISTING FACTS:
{chr(10).join(f"- [{f['fact_id']}]: {f['content']}" for f in similar)}

Analyze for contradiction."""

        try:
            agent = _build_contradiction_agent(self.model)
            result = await asyncio.wait_for(
                agent.run(prompt),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            logger.warning("custodian.llm_timeout", fact_id=fact_id)
            return ContradictionResult(has_contradiction=False)
        except Exception as e:
            logger.error("custodian.llm_error", error=str(e), fact_id=fact_id)
            return ContradictionResult(has_contradiction=False)

        if result.output.confidence < self.min_confidence:
            return ContradictionResult(has_contradiction=False)

        valid_ids = {f["fact_id"] for f in similar}
        supersedes = [fid for fid in result.output.supersedes if fid in valid_ids]

        return ContradictionResult(
            has_contradiction=result.output.has_contradiction and len(supersedes) > 0,
            supersedes_ids=supersedes,
            reason=result.output.reasoning,
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


async def on_custodian_batch_fire(silo_id: str, node_ids: list[str]) -> None:
    """Callback for AsyncBatchTrigger. Processes a batch of nodes."""
    from context_service.mcp.server import get_context_service

    settings = get_settings()
    store = get_context_service().graph_store

    cfg = settings.identities.custodian
    custodian = CustodianIdentity(
        store=store,
        silo_id=silo_id,
        model=cfg.model,
        timeout_seconds=float(cfg.timeout_seconds),
        min_confidence=cfg.min_confidence_for_supersession,
    )

    for node_id in node_ids:
        result = await custodian.check_contradiction(node_id)
        if result.has_contradiction:
            for old_id in result.supersedes_ids:
                await custodian.write_supersession(
                    node_id, old_id, result.reason or "contradiction"
                )
                record_supersession_used("custodian", silo_id=silo_id)
