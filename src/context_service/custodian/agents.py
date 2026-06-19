"""Pydantic-ai Agent instances per visit phase.

CITE v2 removes cluster-based visits. Fast/plan/deep agents are retained
as stubs for backwards compatibility; stitch phase and silo synthesis removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from context_service.config.settings import get_settings
from context_service.custodian.models import (
    BudgetStatus,
    Claim,
    FastPassObservation,
    ProposedEdge,
    VisitPlan,
)
from context_service.custodian.prompt_loader import load_prompt

if TYPE_CHECKING:
    from context_service.custodian.validators import CitationValidator
    from context_service.engine.protocols import HyperGraphStore

FAST_PASS_SYSTEM_PROMPT = load_prompt("prompts/custodian/fast_pass.yaml")
PLAN_SYSTEM_PROMPT = load_prompt("prompts/custodian/plan.yaml")
DEEP_PASS_SYSTEM_PROMPT = load_prompt("prompts/custodian/deep_pass.yaml")


@dataclass
class VisitDeps:
    """Per-visit dependency container injected into every tool call."""

    org_id: str
    silo_id: str
    cluster_id: str
    pass_id: str
    scope: Literal["cluster", "silo"]
    seen_node_ids: set[str] = field(default_factory=set)
    claims_buffer: list[Claim] = field(default_factory=list)
    proposed_edges_buffer: list[ProposedEdge] = field(default_factory=list)
    commit_log: list[dict[str, Any]] = field(default_factory=list)
    finalized: bool = False
    memgraph_client: HyperGraphStore | None = None
    validator: CitationValidator | None = None
    budget: BudgetStatus = field(
        default_factory=lambda: BudgetStatus(
            tokens_remaining=0,
            tool_calls_remaining=0,
            wrap_up_signal=False,
        )
    )
    _phase_tool_call_limit: int = field(default=0)
    _phase_tool_calls_used: int = field(default=0)
    _phase_nominal_tokens: int = field(default=0)
    _phase_soft_signal_ratio: float = field(default=0.69)

    def record_commit(self, event: dict[str, Any]) -> None:
        self.commit_log.append(event)


def build_fast_pass_agent() -> Agent[VisitDeps, FastPassObservation]:
    """Flash-model fast-pass agent. Output is a :class:`FastPassObservation`."""
    settings = get_settings()
    return Agent[VisitDeps, FastPassObservation](
        model=settings.custodian.flash_model,
        deps_type=VisitDeps,
        output_type=FastPassObservation,
        system_prompt=FAST_PASS_SYSTEM_PROMPT,
        retries=8,
    )


def build_plan_agent() -> Agent[VisitDeps, VisitPlan]:
    """Flash-model plan agent. Output is a :class:`VisitPlan`."""
    settings = get_settings()
    return Agent[VisitDeps, VisitPlan](
        model=settings.custodian.flash_model,
        deps_type=VisitDeps,
        output_type=VisitPlan,
        system_prompt=PLAN_SYSTEM_PROMPT,
        retries=8,
    )


def build_deep_pass_agent(model: str | None = None) -> Agent[VisitDeps, str]:
    """Deep-pass agent -- produces side effects via tool calls."""
    settings = get_settings()
    return Agent[VisitDeps, str](
        model=model or settings.custodian.flash_model,
        deps_type=VisitDeps,
        output_type=str,
        system_prompt=DEEP_PASS_SYSTEM_PROMPT,
        retries=8,
    )


def fast_pass_limits() -> UsageLimits:
    """UsageLimits for phase 1."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.fast_pass_hard_tokens,
        request_limit=settings.custodian.fast_pass_request_limit,
    )


def plan_limits() -> UsageLimits:
    """UsageLimits for phase 2."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.plan_nominal_tokens * 3,
        request_limit=2,
    )


def deep_pass_limits() -> UsageLimits:
    """UsageLimits for phase 3."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.deep_pass_hard_tokens,
        request_limit=20,
    )


# --- Lazy singletons for tool registration ---

_fast_pass_agent: Agent[VisitDeps, FastPassObservation] | None = None
_plan_agent: Agent[VisitDeps, VisitPlan] | None = None
_deep_pass_agent: Agent[VisitDeps, str] | None = None


def get_fast_pass_agent() -> Agent[VisitDeps, FastPassObservation]:
    global _fast_pass_agent
    if _fast_pass_agent is None:
        _fast_pass_agent = build_fast_pass_agent()
    return _fast_pass_agent


def get_plan_agent() -> Agent[VisitDeps, VisitPlan]:
    global _plan_agent
    if _plan_agent is None:
        _plan_agent = build_plan_agent()
    return _plan_agent


def get_deep_pass_agent() -> Agent[VisitDeps, str]:
    global _deep_pass_agent
    if _deep_pass_agent is None:
        from context_service.custodian.tools import (
            commit_claim,
            commit_inferred_relation,
            finalize_visit,
        )

        _deep_pass_agent = build_deep_pass_agent()
        _deep_pass_agent.tool(commit_claim)
        _deep_pass_agent.tool(commit_inferred_relation)
        _deep_pass_agent.tool(finalize_visit)
    return _deep_pass_agent


__all__ = [
    "VisitDeps",
    "build_deep_pass_agent",
    "build_fast_pass_agent",
    "build_plan_agent",
    "deep_pass_limits",
    "fast_pass_limits",
    "get_deep_pass_agent",
    "get_fast_pass_agent",
    "get_plan_agent",
    "plan_limits",
]
