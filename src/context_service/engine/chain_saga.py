"""Saga pattern for ReasoningChain writes across Postgres and Memgraph."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from context_service.engine.postgres_store import PostgresStore
    from context_service.models.inference import ChainStep

log = structlog.get_logger()

_MAX_COMPENSATION_RETRIES = 3


class ChainSagaWriter:
    """Writes ReasoningChain with Postgres-first saga and compensation.

    Write order:
    1. Upsert full steps payload to Postgres (idempotent via ON CONFLICT).
    2. Upsert summary projection to Memgraph.

    On Memgraph failure: compensate by deleting the Postgres row.
    If compensation also fails: dead-letter via add_orphaned_chain.
    """

    def __init__(self, postgres_store: PostgresStore, memgraph_store: Any) -> None:
        self._pg = postgres_store
        self._mg = memgraph_store

    async def write_chain(
        self,
        chain_id: UUID,
        silo_id: UUID,
        steps: list[ChainStep],
        produced_by_model: str,
        produced_by_agent_id: str,
        query_context_hash: str | None = None,
        status: str = "draft",
        source: str = "agent_explicit",
        conclusion: str | None = None,
        evidence_used: list[str] | None = None,
    ) -> None:
        """Write chain with saga pattern: Postgres first, then Memgraph.

        On Memgraph failure, compensates by deleting the Postgres row.
        Retries compensation up to _MAX_COMPENSATION_RETRIES times before
        falling back to the dead-letter table.
        """
        step_count = len(steps)
        all_premise_refs: list[str] = list(evidence_used) if evidence_used else []
        for step in steps:
            all_premise_refs.extend(step.premise_refs)
        outcome = self._derive_outcome(steps)

        try:
            steps_data = [s.model_dump(mode="json") for s in steps]
            first_step = json.dumps(steps_data[0]) if steps_data else None
            final_step = json.dumps(steps_data[-1]) if steps_data else None
        except (TypeError, ValueError) as exc:
            log.error("saga_serialization_failed", chain_id=str(chain_id), error=str(exc))
            raise

        await self._pg.upsert_chain_steps(chain_id, silo_id, steps_data)

        try:
            await self._mg.upsert_reasoning_chain(
                chain_id=str(chain_id),
                silo_id=str(silo_id),
                step_count=step_count,
                first_step=first_step,
                final_step=final_step,
                outcome=outcome,
                all_premise_refs=all_premise_refs,
                produced_by_model=produced_by_model,
                produced_by_agent_id=produced_by_agent_id,
                query_context_hash=query_context_hash,
                status=status,
                source=source,
                conclusion=conclusion,
            )
        except Exception as exc:
            await self._compensate(chain_id, silo_id, str(exc))
            raise

    async def _compensate(self, chain_id: UUID, silo_id: UUID, error: str) -> None:
        """Attempt to delete Postgres row; dead-letter on repeated failure."""
        for attempt in range(_MAX_COMPENSATION_RETRIES):
            try:
                await self._pg.delete_chain_steps(chain_id)
                log.info("saga_compensation_success", chain_id=str(chain_id))
                return
            except Exception as comp_err:
                log.warning(
                    "saga_compensation_retry",
                    chain_id=str(chain_id),
                    attempt=attempt + 1,
                    error=str(comp_err),
                )

        log.error("saga_compensation_failed", chain_id=str(chain_id), error=error)
        await self._pg.add_orphaned_chain(chain_id, silo_id, error)

    def _derive_outcome(self, steps: list[ChainStep]) -> str | None:
        """Derive outcome label from final step confidence."""
        if not steps:
            return None
        final_confidence = steps[-1].confidence
        if final_confidence >= 0.8:
            return "success"
        if final_confidence >= 0.5:
            return "inconclusive"
        return "failure"


__all__ = ["ChainSagaWriter"]
