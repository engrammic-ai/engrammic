"""MCP tool: context_crystallize - Promote WorkingHypothesiss to durable Commitments."""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from context_service.services.models import derive_silo_id
from context_service.telemetry.metrics import record_mcp_tool

if TYPE_CHECKING:
    from fastmcp import FastMCP


async def _crystallize_one(
    store: Any,
    belief_id: str,
    silo_id: str,
    reason: str,
    created_at: str,
    rationale_chain_id: str | None = None,
) -> tuple[str, float] | None:
    """Crystallize a single WorkingHypothesis; returns (commitment_id, confidence) or None on miss."""
    from context_service.db import queries as q

    commitment_id = str(uuid.uuid4())
    rows = await store.execute_write(
        q.CRYSTALLIZE_TO_COMMITMENT,
        {
            "belief_id": belief_id,
            "silo_id": silo_id,
            "commitment_id": commitment_id,
            "reason": reason,
            "created_at": created_at,
            "valid_from": created_at,
            "rationale_chain_id": rationale_chain_id,
        },
    )
    if not rows:
        return None
    row = rows[0]
    confidence = float(row.get("confidence", 1.0) or 1.0)
    return commitment_id, confidence


async def _context_crystallize(
    belief_ids: list[str],
    silo_id: str,
    reason: str | None = None,
    chain_id: str | None = None,
) -> dict[str, Any]:
    """Internal implementation for testing."""
    import structlog

    from context_service.config.settings import get_settings
    from context_service.mcp.server import get_context_service

    logger = structlog.get_logger(__name__)

    if not belief_ids:
        return {"error": "missing_belief_ids", "message": "belief_ids must be non-empty"}

    store = get_context_service().graph_store

    # Validator intercept
    settings = get_settings()
    if settings.identities.validator.enabled:
        from context_service.custodian.identities.validator import ValidatorIdentity

        validator = ValidatorIdentity(
            store=store,
            silo_id=silo_id,
            model=settings.identities.validator.model,
            timeout_seconds=settings.identities.validator.timeout_seconds,
        )

        try:
            validation = await asyncio.wait_for(
                validator.validate_crystallize(belief_ids),
                timeout=settings.identities.validator.timeout_seconds,
            )
            if not validation.valid:
                if settings.identities.validator.fail_open:
                    logger.warning(
                        "validator.failed_open",
                        reasons=validation.reasons,
                        identity="validator",
                    )
                else:
                    return {"error": "validation_failed", "reasons": validation.reasons}
        except TimeoutError:
            logger.warning("validator.timeout", identity="validator")

    now = datetime.now(UTC).isoformat()
    effective_reason = reason or "crystallized"

    results = await asyncio.gather(
        *[
            _crystallize_one(store, bid, silo_id, effective_reason, now, chain_id)
            for bid in belief_ids
        ]
    )

    commitment_ids = [r[0] for r in results if r is not None]
    confidences = [r[1] for r in results if r is not None]
    crystallized_belief_ids = [
        bid for bid, r in zip(belief_ids, results, strict=True) if r is not None
    ]
    not_found = [bid for bid, r in zip(belief_ids, results, strict=True) if r is None]

    response: dict[str, Any] = {
        "commitment_ids": commitment_ids,
        "crystallized_belief_ids": crystallized_belief_ids,
        "confidences": confidences,
    }
    if not_found:
        response["not_found"] = not_found
    return response


def register(mcp: FastMCP) -> None:
    """Register the context_crystallize tool."""

    @mcp.tool(
        name="context_crystallize",
        description=(
            "Promote one or more WorkingHypothesiss to durable Commitments. "
            "Each crystallized belief creates a Commitment node with SUPERSEDES edges "
            "to any prior active Commitments about the same nodes."
        ),
    )
    async def context_crystallize(
        belief_ids: list[str],
        reason: str | None = None,
        silo_id: str | None = None,
        chain_id: str | None = None,
    ) -> dict[str, Any]:
        """Crystallize WorkingHypothesiss into Commitments.

        Args:
            belief_ids: List of WorkingHypothesis IDs to promote.
            reason: Optional reason stored on SUPERSEDES edges.
            silo_id: UUID of the silo. Optional; defaults to the org's primary silo
                derived from auth.
            chain_id: Optional reasoning chain ID (ReasoningChain node) that motivated
                this crystallization. Stored as rationale_chain_id on each resulting
                Commitment node.

        Returns:
            {commitment_ids: list[str], crystallized_belief_ids: list[str], not_found?: list[str]}
            where crystallized_belief_ids lists the belief_ids that were successfully promoted
            and not_found lists any IDs that did not match a WorkingHypothesis in the silo.
        """
        from context_service.mcp.server import get_mcp_auth_context, get_silo_service
        from context_service.services.silo import validate_silo_ownership

        auth = await get_mcp_auth_context()
        if silo_id is not None:
            err = await validate_silo_ownership(get_silo_service(), silo_id, auth.org_id)
            if err is not None:
                return err
        resolved_silo_id = silo_id or str(derive_silo_id(auth.org_id))
        start = time.perf_counter()
        success = True
        try:
            result = await _context_crystallize(
                belief_ids=belief_ids,
                silo_id=resolved_silo_id,
                reason=reason,
                chain_id=chain_id,
            )
            return result
        except Exception:
            success = False
            raise
        finally:
            record_mcp_tool(
                "context_crystallize", (time.perf_counter() - start) * 1000, success=success
            )
