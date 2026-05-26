from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from context_service.config.logging import get_logger

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore

logger = get_logger(__name__)


class ValidationResult(BaseModel):
    valid: bool
    validation_skipped: bool = False
    reasons: list[str] = []


PREMISE_EXISTS_QUERY = """
UNWIND $premise_ids AS pid
OPTIONAL MATCH (n {id: pid, silo_id: $silo_id})
RETURN pid AS premise_id, n IS NOT NULL AS exists
"""

# Batched query to get premises for multiple hypotheses in one round-trip.
# Filters by silo_id to prevent cross-tenant data leakage.
GET_HYPOTHESIS_PREMISES_BATCH = """
UNWIND $hypothesis_ids AS hid
MATCH (h:WorkingHypothesis {id: hid, silo_id: $silo_id})-[:DERIVED_FROM]->(p)
RETURN p.id AS premise_id
"""


@dataclass
class ValidatorIdentity:
    """Validates reasoning structure on crystallize (T13)."""

    store: HyperGraphStore
    silo_id: str
    model: str = "google-vertex:gemini-2.5-pro"
    timeout_seconds: float = 5.0

    async def validate_premises(self, premise_ids: list[str]) -> ValidationResult:
        """Check all premise node IDs exist in silo."""
        if not premise_ids:
            return ValidationResult(valid=True)

        rows = await self.store.execute_query(
            PREMISE_EXISTS_QUERY,
            {"premise_ids": premise_ids, "silo_id": self.silo_id},
        )

        missing = [r["premise_id"] for r in rows if not r["exists"]]
        if missing:
            return ValidationResult(
                valid=False,
                reasons=[f"Missing premises: {missing}"],
            )

        return ValidationResult(valid=True)

    async def validate_crystallize(self, hypothesis_ids: list[str]) -> ValidationResult:
        """Full validation for crystallize. Called from context_crystallize MCP tool."""
        # For now, just validate premises exist
        # TODO: Add LLM-based reasoning structure validation

        if not hypothesis_ids:
            return ValidationResult(valid=True)

        # Batch query to get all premises in one round-trip (fixes N+1)
        # Also filters by silo_id to prevent cross-tenant leakage
        rows = await self.store.execute_query(
            GET_HYPOTHESIS_PREMISES_BATCH,
            {"hypothesis_ids": hypothesis_ids, "silo_id": self.silo_id},
        )
        all_premises = [r["premise_id"] for r in rows]

        return await self.validate_premises(all_premises)
