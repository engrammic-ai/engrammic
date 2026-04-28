"""Pydantic-ai Agent instances per visit phase.

One Agent per phase (fast, plan, deep, stitch) with its own output_type,
system prompt, and UsageLimits envelope. Tools are registered in
context_service/custodian/tools.py via @agent.tool decorators -- this module
defines only the Agent instances and their deps contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from primitives.eag.agents import DepsProtocol  # noqa: F401  # type: ignore[import-untyped]
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from context_service.core.settings import get_settings
from context_service.custodian.models import (
    BudgetStatus,
    Claim,
    FastPassObservation,
    ProposedEdge,
    StitchedSummary,
    VisitPlan,
)
from context_service.custodian.output_recovery import patch_agent_output_validators
from context_service.custodian.prompt_loader import load_prompt

if TYPE_CHECKING:
    from context_service.custodian.validators import CitationValidator
    from context_service.stores.memgraph import MemgraphClient

FAST_PASS_SYSTEM_PROMPT = load_prompt("prompts/custodian/fast_pass.yaml")
PLAN_SYSTEM_PROMPT = load_prompt("prompts/custodian/plan.yaml")
DEEP_PASS_SYSTEM_PROMPT = load_prompt("prompts/custodian/deep_pass.yaml")
STITCH_SYSTEM_PROMPT = load_prompt("prompts/custodian/stitch.yaml")


@dataclass
class VisitDeps:
    """Per-visit dependency container injected into every tool call.

    Mutated in place by tools as the visit progresses:

    - ``seen_node_ids`` grows with every node_id returned from a tool.
    - ``claims_buffer`` appends on every commit_claim.
    - ``budget`` is replaced (not mutated) after each tool call with a fresh
      :class:`BudgetStatus` reflecting tokens/tool_calls consumed so far.

    The Memgraph / Redis / metrics clients are NOT stored here -- they belong
    to the visit orchestrator which constructs ``VisitDeps`` per visit and
    passes them to tools via closures. Keep this dataclass minimal and
    serialization-friendly for tracing.
    """

    org_id: str
    silo_id: str
    cluster_id: str
    pass_id: str
    scope: Literal["cluster", "silo"]
    seen_node_ids: set[str] = field(default_factory=set)
    claims_buffer: list[Claim] = field(default_factory=list)
    proposed_edges_buffer: list[ProposedEdge] = field(default_factory=list)
    # Chronological log of every commit_* and finalize_visit tool call.
    commit_log: list[dict[str, Any]] = field(default_factory=list)
    # Set by ``finalize_visit`` tool; orchestrator inspects this after ``agent.run``
    # returns to decide whether to invoke WritePath.write_visit.
    finalized: bool = False
    # Per-visit infrastructure handles. Populated by the orchestrator when it
    # constructs VisitDeps; tools registered on the module-level Agent singletons
    # read them off ``ctx.deps`` (the singletons cannot capture per-visit clients
    # via closure). Unit tests inject fakes directly.
    memgraph_client: MemgraphClient | None = None
    validator: CitationValidator | None = None
    # Budget defaults to a "full" status; orchestrator replaces it between turns.
    budget: BudgetStatus = field(
        default_factory=lambda: BudgetStatus(
            tokens_remaining=0,
            tool_calls_remaining=0,
            wrap_up_signal=False,
        )
    )
    # Per-phase budget tracking fields. Populated by the orchestrator before
    # each phase; _rebuild_budget in tools.py reads and mutates these fields.
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
    """Deep-pass agent -- produces side effects via tool calls. The nominal
    ``output_type`` is ``str`` (pydantic-ai's default for unstructured text
    output); the orchestrator ignores the final text and only consumes the
    committed claims buffer on ``deps``. Model selection is dynamic: pass
    ``settings.custodian.pro_model`` when fast-pass signalled complexity=high,
    otherwise flash.
    """
    settings = get_settings()
    return Agent[VisitDeps, str](
        model=model or settings.custodian.flash_model,
        deps_type=VisitDeps,
        output_type=str,  # side-effects-only: final text is ignored
        system_prompt=DEEP_PASS_SYSTEM_PROMPT,
        # Tool-call validation retries. Default 1 is too strict: the model
        # routinely returns a malformed commit_claim / commit_inferred_relation
        # payload (wrong field name, missing enum value) for several attempts
        # before self-correcting from pydantic-ai's RetryPromptPart feedback.
        retries=8,
    )


def build_stitch_agent() -> Agent[VisitDeps, StitchedSummary]:
    """Flash-model stitch agent. Output is a :class:`StitchedSummary`."""
    settings = get_settings()
    return Agent[VisitDeps, StitchedSummary](
        model=settings.custodian.flash_model,
        deps_type=VisitDeps,
        output_type=StitchedSummary,
        system_prompt=STITCH_SYSTEM_PROMPT,
        retries=8,
    )


def fast_pass_limits() -> UsageLimits:
    """UsageLimits for phase 1. Hard == nominal (no wrap-up headroom needed)."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.fast_pass_hard_tokens,
        tool_calls_limit=settings.custodian.fast_pass_tool_calls_limit,
        request_limit=settings.custodian.fast_pass_request_limit,
    )


def plan_limits() -> UsageLimits:
    """UsageLimits for phase 2. Soft target only -- not hard-metered."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.plan_nominal_tokens * 3,  # loose cap
        tool_calls_limit=0,  # plan phase does not call tools
        request_limit=2,
    )


def deep_pass_limits() -> UsageLimits:
    """UsageLimits for phase 3.

    Hard output cap protects against runaway responses; tool_calls_limit +
    request_limit protect against agent loops. total_tokens_limit was
    dropped 2026-04-26 -- post-hoc absolute cap fired at +5% over with no
    streaming abort, killing dense-but-valid clusters. Industry pattern
    (pydantic-ai docs, LangGraph) uses request_limit + tool_calls_limit as
    primary guards; output cap as the per-call ceiling.
    """
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.deep_pass_hard_tokens,
        tool_calls_limit=30,
        request_limit=20,
    )


def stitch_limits() -> UsageLimits:
    """UsageLimits for phase 4. Small envelope; no tool calls."""
    settings = get_settings()
    return UsageLimits(
        output_tokens_limit=settings.custodian.stitch_hard_tokens,
        tool_calls_limit=0,
        request_limit=1,
    )


# --- Module-level singletons for tool registration ---
# These are instantiated once at import time. The build_* factories are
# retained for testability -- tests can still construct isolated agents.

fast_pass_agent = build_fast_pass_agent()
plan_agent = build_plan_agent()
deep_pass_agent = build_deep_pass_agent()
stitch_agent = build_stitch_agent()

# Patch output validators on all structured-output agents with recovery logic.
# deep_pass_agent uses output_type=str and has no output toolset; patch_* no-ops for it.
patch_agent_output_validators(fast_pass_agent, FastPassObservation, "fast_pass")
patch_agent_output_validators(plan_agent, VisitPlan, "plan")
patch_agent_output_validators(stitch_agent, StitchedSummary, "stitch")


__all__ = [
    "VisitDeps",
    "build_deep_pass_agent",
    "build_fast_pass_agent",
    "build_plan_agent",
    "build_stitch_agent",
    "deep_pass_agent",
    "deep_pass_limits",
    "fast_pass_agent",
    "fast_pass_limits",
    "plan_agent",
    "plan_limits",
    "stitch_agent",
    "stitch_limits",
]
