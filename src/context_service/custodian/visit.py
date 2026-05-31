"""Visit orchestrator: 4-phase runner (fast, plan, deep, stitch) for a single cluster.

Phases:
1. **Fast pass (flash)** -- cheap reconnaissance via fetch_members + fetch_lower_findings.
2. **Plan (flash)** -- decides strategy; may short-circuit to SKIPPED.
3. **Deep pass (flash or pro)** -- side-effects-only agent producing claims via tool calls.
4. **Stitch (flash)** -- assembles a StitchedSummary from committed claims.

After the agent phases, the write path persists the FindingOutput atomically
and a VisitTrace is written to Redis (best-effort, never crashes the visit).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic_ai.exceptions import UsageLimitExceeded

from context_service.config.logging import get_logger
from context_service.config.settings import CustodianSettings, get_settings
from context_service.core.trace_context import trace_scope
from context_service.custodian.agents import (
    VisitDeps,
    build_deep_pass_agent,
    deep_pass_limits,
    fast_pass_limits,
    get_deep_pass_agent,
    get_fast_pass_agent,
    get_plan_agent,
    get_stitch_agent,
    plan_limits,
    stitch_limits,
)
from context_service.custodian.fingerprints import member_fingerprint
from context_service.custodian.metrics import (
    CustodianRejectionMetrics,
    compute_cost_usd,
    record_hard_cap_hit,
    record_pass_cost,
    record_phase_usage,
    record_visit_strategy,
)
from context_service.custodian.models import (
    BudgetStatus,
    FindingOutput,
    VisitStatus,
)
from context_service.custodian.tools import (
    commit_claim,
    commit_inferred_relation,
    fetch_lower_findings,
    fetch_members,
    fetch_neighborhood,
    fetch_node,
    finalize_visit,
    list_edges_of_type,
)
from context_service.custodian.traces import UsageBreakdown, VisitTrace, VisitTraceCache
from context_service.custodian.validators import CitationValidator
from context_service.custodian.write_path import WritePath, WritePathResult
from context_service.db import custodian_read_queries as read_q
from context_service.llm.sanitize import escape_for_prompt

if TYPE_CHECKING:
    from context_service.engine.protocols import HyperGraphStore
    from context_service.stores.redis import RedisClient

PhaseCallback = Callable[[str, str], Awaitable[None]]  # (phase_name, cluster_id) -> None

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class VisitResult:
    """Outcome of a single cluster visit."""

    cluster_id: str
    pass_id: str
    status: VisitStatus
    write_result: WritePathResult | None = None
    usage_breakdown: dict[str, UsageBreakdown] = field(default_factory=dict)
    skipped_reason: str | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Phase budget initialization
# ---------------------------------------------------------------------------


def _init_phase_budget(deps: VisitDeps, phase: str, settings: CustodianSettings) -> None:
    """Reset per-phase budget tracking on deps before running a phase."""
    deps._phase_tool_calls_used = 0

    if phase == "fast":
        deps._phase_nominal_tokens = settings.fast_pass_nominal_tokens
        deps._phase_tool_call_limit = 4
        deps._phase_soft_signal_ratio = 1.0
    elif phase == "plan":
        deps._phase_nominal_tokens = settings.plan_nominal_tokens
        deps._phase_tool_call_limit = 0
        deps._phase_soft_signal_ratio = 1.0
    elif phase == "deep":
        deps._phase_nominal_tokens = settings.deep_pass_nominal_tokens
        deps._phase_tool_call_limit = 30
        deps._phase_soft_signal_ratio = settings.deep_pass_soft_signal_ratio
    elif phase == "stitch":
        deps._phase_nominal_tokens = settings.stitch_nominal_tokens
        deps._phase_tool_call_limit = 0
        deps._phase_soft_signal_ratio = 1.0

    # Set initial budget status for this phase.
    deps.budget = BudgetStatus(
        tokens_remaining=deps._phase_nominal_tokens,
        tool_calls_remaining=deps._phase_tool_call_limit,
        wrap_up_signal=False,
    )


# ---------------------------------------------------------------------------
# Usage extraction
# ---------------------------------------------------------------------------


def _extract_usage(result: Any, model_name: str, elapsed: float) -> UsageBreakdown:
    """Build a UsageBreakdown from a pydantic-ai AgentRunResult."""
    usage = result.usage()
    return UsageBreakdown(
        model=model_name,
        input_tokens=usage.input_tokens or 0,
        output_tokens=usage.output_tokens or 0,
        duration_seconds=round(elapsed, 3),
    )


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _fast_pass_prompt(
    cluster_id: str,
    cluster_level: str,
    cluster_member_count: int,
    naive_summary: str | None,
    child_finding_summaries: list[str],
) -> str:
    parts = [
        f"Cluster: {cluster_id}",
        f"Level: {cluster_level}",
        f"Member count: {cluster_member_count}",
    ]
    if naive_summary:
        parts.append(f"Naive summary: {escape_for_prompt(naive_summary)}")
    if child_finding_summaries:
        parts.append("Child finding summaries:")
        for i, s in enumerate(child_finding_summaries, 1):
            parts.append(f"  {i}. {escape_for_prompt(s)}")
    parts.append(
        "Perform a fast reconnaissance of this cluster. "
        "Use fetch_members to scan the first page of members, "
        "and fetch_lower_findings if child findings exist. "
        "Return your FastPassObservation."
    )
    return "\n".join(parts)


def _plan_prompt(
    observation: Any,
    settings: CustodianSettings,
    cluster_member_count: int,
) -> str:
    parts = [
        "Fast pass observation:",
        f"  cluster_character: {observation.cluster_character}",
        f"  interesting_nodes: {observation.interesting_nodes}",
        f"  suspected_themes: {observation.suspected_themes}",
        f"  complexity: {observation.complexity}",
        f"  needs_deep_pass: {observation.needs_deep_pass}",
        "",
        f"Cluster member count: {cluster_member_count}",
        f"Deep pass budget: {settings.deep_pass_nominal_tokens} tokens, 30 tool calls",
        "",
        "Decide the visit strategy. If the cluster is trivial or the fast pass "
        "captured everything, set strategy='skip' with a reason. Otherwise pick "
        "'confirm_naive', 'deepen', or 'cross_reference' and plan a tool_call_sequence.",
    ]
    return "\n".join(parts)


def _deep_pass_prompt(plan: Any, observation: Any) -> str:
    parts = [
        "Execute the deep pass for this cluster.",
        "",
        f"Strategy: {plan.strategy}",
        f"Planned tool sequence: {plan.tool_call_sequence}",
        f"Stop conditions: {plan.stop_conditions}",
        "",
        f"Cluster character: {observation.cluster_character}",
        f"Suspected themes: {observation.suspected_themes}",
        "",
        "Use the tools to investigate, then commit_claim for each finding "
        "and commit_inferred_relation for any edges you discover. "
        "Call finalize_visit when done. Watch the budget_status in tool "
        "responses and wrap up when wrap_up_signal is True.",
    ]
    return "\n".join(parts)


def _stitch_prompt(claims: list[Any]) -> str:
    parts = ["Stitch the following committed claims into a coherent summary:", ""]
    for i, claim in enumerate(claims):
        citation_ids = ", ".join(c.node_id for c in claim.citations)
        parts.append(f"  [{i}] {claim.text} (cites: {citation_ids})")
    parts.append("")
    parts.append(
        "Produce a StitchedSummary: a list of sentences, each referencing "
        "the claim indices (claim_refs) it draws from."
    )
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Trace helpers
# ---------------------------------------------------------------------------


async def _write_trace_best_effort(
    redis_client: RedisClient,
    settings: CustodianSettings,
    *,
    pass_id: str,
    cluster_id: str,
    org_id: str,
    silo_id: str,
    observation: Any | None,
    plan: Any | None,
    commit_log: list[dict[str, Any]],
    usage_breakdown: dict[str, UsageBreakdown],
    stitch_output: Any | None,
) -> None:
    """Build and write a VisitTrace to Redis. Never raises."""
    try:
        trace = VisitTrace(
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            fast_pass_observation=(observation.model_dump() if observation is not None else None),
            plan=plan.model_dump() if plan is not None else None,
            commit_log=commit_log,
            usage_breakdown=usage_breakdown,
            stitch_output=(stitch_output.model_dump() if stitch_output is not None else None),
            created_at=datetime.now(tz=UTC),
        )
        ttl = settings.redis_trace_ttl_days * 86_400
        cache = VisitTraceCache(redis_client, ttl_seconds=ttl)
        await cache.write(pass_id, cluster_id, trace)
    except Exception:
        logger.warning(
            f"Failed to write visit trace for pass={pass_id} cluster={cluster_id}",
            exc_info=True,
        )


async def _finalize_visit(
    redis_client: RedisClient,
    settings: CustodianSettings,
    *,
    pass_id: str,
    cluster_id: str,
    org_id: str,
    silo_id: str,
    observation: Any | None,
    plan: Any | None,
    commit_log: list[dict[str, Any]],
    usage_breakdown: dict[str, UsageBreakdown],
    status: VisitStatus,
    skipped_reason: str | None = None,
    error: str | None = None,
) -> VisitResult:
    """Write trace and return a VisitResult for non-write-path exits (skip, crash)."""
    await _write_trace_best_effort(
        redis_client,
        settings,
        pass_id=pass_id,
        cluster_id=cluster_id,
        org_id=org_id,
        silo_id=silo_id,
        observation=observation,
        plan=plan,
        commit_log=commit_log,
        usage_breakdown=usage_breakdown,
        stitch_output=None,
    )
    return VisitResult(
        cluster_id=cluster_id,
        pass_id=pass_id,
        status=status,
        usage_breakdown=usage_breakdown,
        skipped_reason=skipped_reason,
        error=error,
    )


async def _write_and_trace(
    *,
    memgraph_client: HyperGraphStore,
    redis_client: RedisClient,
    settings: CustodianSettings,
    deps: VisitDeps,
    observation: Any | None,
    plan: Any | None,
    stitch_summary: Any | None,
    usage_breakdown: dict[str, UsageBreakdown],
    model_name: str | None,
) -> VisitResult:
    """Run write path + trace for the happy path and partial-write paths."""
    cluster_id = deps.cluster_id
    pass_id = deps.pass_id

    try:
        # Fetch member IDs for fingerprint.
        member_ids = await read_q.fetch_cluster_member_ids(
            memgraph_client,
            cluster_id=cluster_id,
            silo_id=deps.silo_id,
        )

        # Race-guard: a concurrent clustering_job may have wiped & rebuilt the
        # cluster hierarchy between visit-start and write-time, so the
        # cluster_id this visit holds is now orphaned. Detect that here and
        # skip cleanly instead of crashing inside the MERGE pipeline (the
        # cluster-scope MERGE's MATCH (c:Cluster {id: $cluster_id}) would
        # return zero rows, and merge_result.single() would be None).
        if deps.scope == "cluster" and not member_ids:
            logger.warning(
                f"Cluster {cluster_id} disappeared between visit-start and write "
                f"(pass={pass_id} silo={deps.silo_id}); likely a concurrent "
                f"clear_and_build_hierarchy_atomic. Skipping write."
            )
            return await _finalize_visit(
                redis_client,
                settings,
                pass_id=pass_id,
                cluster_id=cluster_id,
                org_id=deps.org_id,
                silo_id=deps.silo_id,
                observation=observation,
                plan=plan,
                commit_log=deps.commit_log,
                usage_breakdown=usage_breakdown,
                status=VisitStatus.SKIPPED,
                skipped_reason="cluster_disappeared",
            )

        fp = member_fingerprint(member_ids)

        finding = FindingOutput(
            cluster_id=cluster_id,
            silo_id=deps.silo_id,
            scope=deps.scope,
            claims=list(deps.claims_buffer),
            inferred_relations=list(deps.proposed_edges_buffer),
            summary=stitch_summary,
        )

        validator = CitationValidator(memgraph_client)
        write_path = WritePath(memgraph_client, validator)
        visit_ref = f"custodian:visit:{pass_id}:{cluster_id}"

        write_result = await write_path.write_visit(
            finding=finding,
            pass_id=pass_id,
            cluster_size=len(member_ids),
            seen_node_ids=deps.seen_node_ids,
            org_id=deps.org_id,
            visit_ref=visit_ref,
            model_name=model_name,
            member_fingerprint=fp,
        )

        # Write trace (best-effort).
        await _write_trace_best_effort(
            redis_client,
            settings,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=deps.org_id,
            silo_id=deps.silo_id,
            observation=observation,
            plan=plan,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            stitch_output=stitch_summary,
        )

        return VisitResult(
            cluster_id=cluster_id,
            pass_id=pass_id,
            status=VisitStatus.COMPLETED,
            write_result=write_result,
            usage_breakdown=usage_breakdown,
        )

    except Exception as exc:
        logger.error(
            f"Write path crashed for pass={pass_id} cluster={cluster_id}: {exc}",
            exc_info=True,
        )
        # Trace best-effort even on write crash.
        await _write_trace_best_effort(
            redis_client,
            settings,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=deps.org_id,
            silo_id=deps.silo_id,
            observation=observation,
            plan=plan,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            stitch_output=stitch_summary,
        )
        return VisitResult(
            cluster_id=cluster_id,
            pass_id=pass_id,
            status=VisitStatus.CRASHED,
            usage_breakdown=usage_breakdown,
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


async def run_visit(
    *,
    cluster_id: str,
    org_id: str,
    silo_id: str,
    pass_id: str,
    cluster_level: str,
    cluster_member_count: int,
    naive_summary: str | None,
    child_finding_summaries: list[str],
    memgraph_client: HyperGraphStore,
    redis_client: RedisClient,
    phase_callback: PhaseCallback | None = None,
) -> VisitResult:
    """Run a 4-phase visit against a single cluster.

    All parameters are keyword-only. The Prefect flow pre-fetches cluster
    metadata and passes it here.
    """
    async with trace_scope(
        org_id=org_id,
        silo_id=silo_id,
        visit_id=f"{pass_id}:{cluster_id}",
        pass_id=pass_id,
        cluster_id=cluster_id,
    ):
        return await _run_visit_body(
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            pass_id=pass_id,
            cluster_level=cluster_level,
            cluster_member_count=cluster_member_count,
            naive_summary=naive_summary,
            child_finding_summaries=child_finding_summaries,
            memgraph_client=memgraph_client,
            redis_client=redis_client,
            phase_callback=phase_callback,
        )


async def _run_visit_body(
    *,
    cluster_id: str,
    org_id: str,
    silo_id: str,
    pass_id: str,
    cluster_level: str,
    cluster_member_count: int,
    naive_summary: str | None,
    child_finding_summaries: list[str],
    memgraph_client: HyperGraphStore,
    redis_client: RedisClient,
    phase_callback: PhaseCallback | None = None,
) -> VisitResult:
    ov = get_settings().custodian

    _rejection_metrics = CustodianRejectionMetrics()
    deps = VisitDeps(
        org_id=org_id,
        silo_id=silo_id,
        cluster_id=cluster_id,
        pass_id=pass_id,
        scope="cluster",
        memgraph_client=memgraph_client,
        validator=CitationValidator(memgraph_client, metrics=_rejection_metrics),
    )

    usage_breakdown: dict[str, UsageBreakdown] = {}
    observation = None
    plan = None
    stitch_summary = None
    model_name: str | None = ov.flash_model

    # ------------------------------------------------------------------
    # PHASE 1 -- Fast pass (flash)
    # ------------------------------------------------------------------
    _init_phase_budget(deps, "fast", ov)
    prompt = _fast_pass_prompt(
        cluster_id,
        cluster_level,
        cluster_member_count,
        naive_summary,
        child_finding_summaries,
    )

    try:
        t0 = time.monotonic()
        fast_result = await asyncio.wait_for(
            get_fast_pass_agent().run(prompt, deps=deps, usage_limits=fast_pass_limits()),
            timeout=30.0,
        )
        elapsed = time.monotonic() - t0
        observation = fast_result.output
        usage_breakdown["fast"] = _extract_usage(fast_result, ov.flash_model, elapsed)
        record_phase_usage(
            "fast",
            cluster_level,
            org_id,
            ov.flash_model,
            (usage_breakdown["fast"].input_tokens + usage_breakdown["fast"].output_tokens),
            elapsed,
        )
        if phase_callback:
            await phase_callback("fast", cluster_id)
    except UsageLimitExceeded as exc:
        logger.info(f"Fast pass budget exceeded for cluster={cluster_id}: {exc}")
        return await _finalize_visit(
            redis_client,
            ov,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            observation=None,
            plan=None,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            status=VisitStatus.SKIPPED,
            skipped_reason="fast_pass_budget_exceeded",
        )
    except Exception as exc:
        logger.error(f"Fast pass crashed for cluster={cluster_id}: {exc}", exc_info=True)
        return await _finalize_visit(
            redis_client,
            ov,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            observation=None,
            plan=None,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            status=VisitStatus.CRASHED,
            error=str(exc),
        )

    # ------------------------------------------------------------------
    # PHASE 2 -- Plan (flash)
    # ------------------------------------------------------------------
    _init_phase_budget(deps, "plan", ov)
    prompt = _plan_prompt(observation, ov, cluster_member_count)

    try:
        t0 = time.monotonic()
        plan_result = await asyncio.wait_for(
            get_plan_agent().run(prompt, deps=deps, usage_limits=plan_limits()),
            timeout=20.0,
        )
        elapsed = time.monotonic() - t0
        plan = plan_result.output
        usage_breakdown["plan"] = _extract_usage(plan_result, ov.flash_model, elapsed)
        record_phase_usage(
            "plan",
            cluster_level,
            org_id,
            ov.flash_model,
            (usage_breakdown["plan"].input_tokens + usage_breakdown["plan"].output_tokens),
            elapsed,
        )
        record_visit_strategy(plan.strategy, cluster_level)
        if phase_callback:
            await phase_callback("plan", cluster_id)
    except UsageLimitExceeded as exc:
        logger.info(f"Plan phase budget exceeded for cluster={cluster_id}: {exc}")
        return await _finalize_visit(
            redis_client,
            ov,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            observation=observation,
            plan=None,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            status=VisitStatus.SKIPPED,
            skipped_reason="plan_budget_exceeded",
        )
    except Exception as exc:
        logger.error(f"Plan phase crashed for cluster={cluster_id}: {exc}", exc_info=True)
        return await _finalize_visit(
            redis_client,
            ov,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            observation=observation,
            plan=None,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            status=VisitStatus.CRASHED,
            error=str(exc),
        )

    # Short-circuit: planner says skip.
    if plan.strategy == "skip":
        return await _finalize_visit(
            redis_client,
            ov,
            pass_id=pass_id,
            cluster_id=cluster_id,
            org_id=org_id,
            silo_id=silo_id,
            observation=observation,
            plan=plan,
            commit_log=deps.commit_log,
            usage_breakdown=usage_breakdown,
            status=VisitStatus.SKIPPED,
            skipped_reason=plan.skip_reason or "plan_strategy_skip",
        )

    # ------------------------------------------------------------------
    # PHASE 3 -- Deep pass (flash or pro)
    # ------------------------------------------------------------------
    skip_deep = cluster_member_count < ov.cluster_min_members_for_deep_pass

    if not skip_deep:
        use_pro = observation.complexity == "high"

        if use_pro:
            model_name = ov.pro_model
            agent = build_deep_pass_agent(model=ov.pro_model)
            # Register all 8 tools on the dynamically-built Pro agent.
            agent.tool(fetch_members)
            agent.tool(fetch_node)
            agent.tool(fetch_neighborhood)
            agent.tool(list_edges_of_type)
            agent.tool(fetch_lower_findings)
            agent.tool(commit_claim)
            agent.tool(commit_inferred_relation)
            agent.tool(finalize_visit)
        else:
            model_name = ov.flash_model
            agent = get_deep_pass_agent()

        _init_phase_budget(deps, "deep", ov)
        prompt = _deep_pass_prompt(plan, observation)

        try:
            t0 = time.monotonic()
            deep_result = await asyncio.wait_for(
                agent.run(prompt, deps=deps, usage_limits=deep_pass_limits()),
                timeout=120.0,
            )
            elapsed = time.monotonic() - t0
            usage_breakdown["deep"] = _extract_usage(deep_result, model_name, elapsed)
            record_phase_usage(
                "deep",
                cluster_level,
                org_id,
                model_name,
                (usage_breakdown["deep"].input_tokens + usage_breakdown["deep"].output_tokens),
                elapsed,
            )
            if phase_callback:
                await phase_callback("deep", cluster_id)
        except UsageLimitExceeded as exc:
            elapsed = time.monotonic() - t0
            logger.info(
                f"Deep pass budget exceeded for cluster={cluster_id} "
                f"(expected, {len(deps.claims_buffer)} claims buffered): {exc}"
            )
            record_hard_cap_hit("deep")
            # Partial usage -- no result object available.
            usage_breakdown["deep"] = UsageBreakdown(
                model=model_name,
                input_tokens=0,
                output_tokens=0,
                duration_seconds=round(elapsed, 3),
            )
            # Proceed to stitch with whatever claims were committed.
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.error(f"Deep pass crashed for cluster={cluster_id}: {exc}", exc_info=True)
            usage_breakdown["deep"] = UsageBreakdown(
                model=model_name,
                input_tokens=0,
                output_tokens=0,
                duration_seconds=round(elapsed, 3),
            )
            if deps.claims_buffer:
                # Attempt partial write with whatever claims exist.
                return await _write_and_trace(
                    memgraph_client=memgraph_client,
                    redis_client=redis_client,
                    settings=ov,
                    deps=deps,
                    observation=observation,
                    plan=plan,
                    stitch_summary=None,
                    usage_breakdown=usage_breakdown,
                    model_name=model_name,
                )
            return await _finalize_visit(
                redis_client,
                ov,
                pass_id=pass_id,
                cluster_id=cluster_id,
                org_id=org_id,
                silo_id=silo_id,
                observation=observation,
                plan=plan,
                commit_log=deps.commit_log,
                usage_breakdown=usage_breakdown,
                status=VisitStatus.CRASHED,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # PHASE 4 -- Stitch (flash)
    # ------------------------------------------------------------------
    if deps.claims_buffer:
        _init_phase_budget(deps, "stitch", ov)
        prompt = _stitch_prompt(deps.claims_buffer)

        try:
            t0 = time.monotonic()
            stitch_result = await asyncio.wait_for(
                get_stitch_agent().run(prompt, deps=deps, usage_limits=stitch_limits()),
                timeout=30.0,
            )
            elapsed = time.monotonic() - t0
            stitch_summary = stitch_result.output
            usage_breakdown["stitch"] = _extract_usage(stitch_result, ov.flash_model, elapsed)
            record_phase_usage(
                "stitch",
                cluster_level,
                org_id,
                ov.flash_model,
                (usage_breakdown["stitch"].input_tokens + usage_breakdown["stitch"].output_tokens),
                elapsed,
            )
            if phase_callback:
                await phase_callback("stitch", cluster_id)
        except UsageLimitExceeded as exc:
            elapsed = time.monotonic() - t0
            logger.info(f"Stitch budget exceeded for cluster={cluster_id}: {exc}")
            stitch_summary = None
            usage_breakdown["stitch"] = UsageBreakdown(
                model=ov.flash_model,
                input_tokens=0,
                output_tokens=0,
                duration_seconds=round(elapsed, 3),
            )
        except Exception as exc:
            elapsed = time.monotonic() - t0
            logger.warning(f"Stitch crashed for cluster={cluster_id}: {exc}", exc_info=True)
            stitch_summary = None
            usage_breakdown["stitch"] = UsageBreakdown(
                model=ov.flash_model,
                input_tokens=0,
                output_tokens=0,
                duration_seconds=round(elapsed, 3),
            )

    # ------------------------------------------------------------------
    # WRITE PATH
    # ------------------------------------------------------------------
    # Compute and record total visit cost before exiting.
    visit_cost = sum(
        compute_cost_usd(u.model, u.input_tokens, u.output_tokens) for u in usage_breakdown.values()
    )
    record_pass_cost(pass_id, org_id, visit_cost)

    if deps.claims_buffer:
        return await _write_and_trace(
            memgraph_client=memgraph_client,
            redis_client=redis_client,
            settings=ov,
            deps=deps,
            observation=observation,
            plan=plan,
            stitch_summary=stitch_summary,
            usage_breakdown=usage_breakdown,
            model_name=model_name,
        )

    # No claims produced (deep pass skipped or produced nothing).
    return await _finalize_visit(
        redis_client,
        ov,
        pass_id=pass_id,
        cluster_id=cluster_id,
        org_id=org_id,
        silo_id=silo_id,
        observation=observation,
        plan=plan,
        commit_log=deps.commit_log,
        usage_breakdown=usage_breakdown,
        status=VisitStatus.COMPLETED,
        skipped_reason="no_claims_produced",
    )


__all__ = [
    "PhaseCallback",
    "VisitResult",
    "run_visit",
]
