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

    async def validate_crystallize(
        self, hypothesis_ids: list[str]
    ) -> ValidationResult:
        """Full validation for crystallize. Called from context_crystallize MCP tool."""
        # For now, just validate premises exist
        # TODO: Add LLM-based reasoning structure validation

        all_premises = []
        for hid in hypothesis_ids:
            rows = await self.store.execute_query(
                "MATCH (h:WorkingHypothesis {id: $id})-[:DERIVED_FROM]->(p) RETURN p.id AS premise_id",
                {"id": hid},
            )
            all_premises.extend([r["premise_id"] for r in rows])

        return await self.validate_premises(all_premises)
