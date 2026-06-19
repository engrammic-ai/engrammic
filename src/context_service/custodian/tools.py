"""Tool implementations for the Custodian visit phases.

CITE v2 removes cluster-based visits. Most tools are deprecated stubs.
Only commit_claim, commit_inferred_relation, and finalize_visit remain
for backwards compatibility with any code that imports them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext

from context_service.custodian.agents import VisitDeps
from context_service.custodian.models import (
    BudgetStatus,
    Claim,
    ProposedEdge,
)


def wrap_node_content(node_id: str, raw_content: str) -> str:
    """Wrap raw user content in the injection-defence delimiter."""
    return f'<node_content id="{node_id}">\n{raw_content}\n</node_content>'


class CommitClaimResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    rejection_reason: str | None = None
    offending_node_ids: list[str] = []
    budget_status: BudgetStatus


class CommitInferredRelationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    rejection_reason: str | None = None
    offending_node_ids: list[str] = []
    budget_status: BudgetStatus


class FinalizeVisitResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finalized: bool
    claims_committed: int
    edges_committed: int
    rejections: int
    budget_status: BudgetStatus


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _require_validator(deps: VisitDeps) -> Any:
    if deps.validator is None:
        raise RuntimeError(
            "VisitDeps.validator is not set -- orchestrator must populate it "
            "before running commit_* tools"
        )
    return deps.validator


def _rebuild_budget(deps: VisitDeps) -> None:
    """Recompute deps.budget after a tool call."""
    deps._phase_tool_calls_used += 1
    tl = deps._phase_tool_call_limit

    if tl > 0:
        call_ratio = deps._phase_tool_calls_used / tl
        estimated_tokens_used = int(call_ratio * deps._phase_nominal_tokens)
        calls_remaining = max(0, tl - deps._phase_tool_calls_used)
    else:
        call_ratio = 0.0
        estimated_tokens_used = 0
        calls_remaining = 0

    tokens_remaining = max(0, deps._phase_nominal_tokens - estimated_tokens_used)
    wrap_up = call_ratio >= deps._phase_soft_signal_ratio or (tl > 0 and calls_remaining <= 2)

    deps.budget = BudgetStatus(
        tokens_remaining=tokens_remaining,
        tool_calls_remaining=calls_remaining,
        wrap_up_signal=wrap_up,
    )


async def commit_claim(
    ctx: RunContext[VisitDeps],
    claim: Claim,
) -> CommitClaimResult:
    """Validate and buffer a single cited claim."""
    deps = ctx.deps
    validator = _require_validator(deps)

    result = await validator.validate_claim(
        claim,
        silo_id=deps.silo_id,
        seen_node_ids=deps.seen_node_ids,
    )

    if result.accepted:
        deps.claims_buffer.append(claim)
        deps.commit_log.append(
            {
                "ts": _now_iso(),
                "event": "commit_claim_accepted",
                "claim_index": len(deps.claims_buffer) - 1,
            }
        )
        _rebuild_budget(deps)
        return CommitClaimResult(accepted=True, budget_status=deps.budget)

    deps.commit_log.append(
        {
            "ts": _now_iso(),
            "event": "commit_claim_rejected",
            "reason": str(result.rejection_reason) if result.rejection_reason else None,
            "offending_node_ids": list(result.offending_node_ids),
        }
    )
    _rebuild_budget(deps)
    return CommitClaimResult(
        accepted=False,
        rejection_reason=str(result.rejection_reason) if result.rejection_reason else None,
        offending_node_ids=list(result.offending_node_ids),
        budget_status=deps.budget,
    )


async def commit_inferred_relation(
    ctx: RunContext[VisitDeps],
    edge: ProposedEdge,
) -> CommitInferredRelationResult:
    """Validate and buffer a single proposed edge."""
    deps = ctx.deps
    validator = _require_validator(deps)

    result = await validator.validate_proposed_edge(
        edge,
        silo_id=deps.silo_id,
        seen_node_ids=deps.seen_node_ids,
    )

    if result.accepted:
        deps.proposed_edges_buffer.append(edge)
        deps.commit_log.append(
            {
                "ts": _now_iso(),
                "event": "commit_inferred_relation_accepted",
                "edge_index": len(deps.proposed_edges_buffer) - 1,
            }
        )
        _rebuild_budget(deps)
        return CommitInferredRelationResult(accepted=True, budget_status=deps.budget)

    deps.commit_log.append(
        {
            "ts": _now_iso(),
            "event": "commit_inferred_relation_rejected",
            "reason": str(result.rejection_reason) if result.rejection_reason else None,
            "offending_node_ids": list(result.offending_node_ids),
        }
    )
    _rebuild_budget(deps)
    return CommitInferredRelationResult(
        accepted=False,
        rejection_reason=str(result.rejection_reason) if result.rejection_reason else None,
        offending_node_ids=list(result.offending_node_ids),
        budget_status=deps.budget,
    )


async def finalize_visit(
    ctx: RunContext[VisitDeps],
) -> FinalizeVisitResult:
    """Mark the visit finalized and return commit counts."""
    deps = ctx.deps
    deps.finalized = True
    rejections = sum(1 for entry in deps.commit_log if entry.get("event", "").endswith("_rejected"))
    deps.commit_log.append(
        {
            "ts": _now_iso(),
            "event": "finalize_visit",
            "claims_committed": len(deps.claims_buffer),
            "edges_committed": len(deps.proposed_edges_buffer),
            "rejections": rejections,
        }
    )
    _rebuild_budget(deps)
    return FinalizeVisitResult(
        finalized=True,
        claims_committed=len(deps.claims_buffer),
        edges_committed=len(deps.proposed_edges_buffer),
        rejections=rejections,
        budget_status=deps.budget,
    )


__all__ = [
    "CommitClaimResult",
    "CommitInferredRelationResult",
    "FinalizeVisitResult",
    "_rebuild_budget",
    "commit_claim",
    "commit_inferred_relation",
    "finalize_visit",
    "wrap_node_content",
]
