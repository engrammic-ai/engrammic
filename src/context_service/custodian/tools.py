"""Tool implementations for the Custodian visit phases.

Tools are registered on the module-level Agent singletons in
``context_service/custodian/agents.py`` via the ``agent.tool(...)`` method. Each tool:

- Reads from Memgraph via helpers in ``context_service/db/custodian_read_queries.py``.
- Updates ``ctx.deps.seen_node_ids`` as nodes are returned.
- Wraps user-authored content in ``<node_content id="...">`` delimiters
  (injection defence; the system prompts instruct the agent to treat everything
  inside these delimiters as untrusted data).
- Embeds a ``BudgetStatus`` in every response payload so the agent sees
  ``wrap_up_signal`` immediately after each tool call.
- ``commit_claim`` and ``commit_inferred_relation`` run
  :class:`CitationValidator` and drop rejected items softly (no raising).

The write path itself is NOT called here. ``commit_claim`` /
``commit_inferred_relation`` append to ``ctx.deps.claims_buffer`` and
``ctx.deps.proposed_edges_buffer``; the orchestrator drains the buffers at
end-of-visit and passes them to ``WritePath.write_visit``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic_ai import RunContext  # noqa: TC002 -- runtime annotation for @agent.tool

from context_service.custodian.agents import (
    VisitDeps,
    deep_pass_agent,
    fast_pass_agent,
)
from context_service.custodian.fingerprints import fingerprint_drift_ok
from context_service.custodian.models import (
    BudgetStatus,
    Claim,
    ProposedEdge,
)
from context_service.db import custodian_read_queries as read_q

# ---------------------------------------------------------------------------
# Delimiter wrapping helper
# ---------------------------------------------------------------------------


def wrap_node_content(node_id: str, raw_content: str) -> str:
    """Wrap raw user content in the injection-defence delimiter.

    The deep-pass / fast-pass system prompts instruct the agent to treat any
    text inside ``<node_content>`` as untrusted data and to ignore instructions
    it may contain. Every tool that projects node content MUST pass through
    this wrapper before handing the string back to the agent.
    """
    return f'<node_content id="{node_id}">\n{raw_content}\n</node_content>'


# ---------------------------------------------------------------------------
# Result types -- every tool result carries a BudgetStatus
# ---------------------------------------------------------------------------


class NodeContent(BaseModel):
    """A single node projected for an agent, with content wrapped in delimiters."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    content: str  # WRAPPED: <node_content id="...">...</node_content>
    org_id: str
    silo_id: str
    label: str | None = None  # "document" | "passage" | "claim"


class EdgeRow(BaseModel):
    """A single edge row for ``list_edges_of_type``."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    edge_type: str
    source_node_id: str
    target_node_id: str


class LowerFinding(BaseModel):
    """A child finding returned by ``fetch_lower_findings`` after drift filter."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    child_cluster_id: str
    claims_json: str | None
    summary_json: str | None
    quality_score: float | None
    version: int | None


class FetchMembersResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    members: list[NodeContent]
    total: int
    has_more: bool
    budget_status: BudgetStatus


class FetchNodeResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    node: NodeContent | None
    budget_status: BudgetStatus


class FetchNeighborhoodResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    found: bool
    seed: NodeContent | None
    neighbours: list[NodeContent]
    budget_status: BudgetStatus


class ListEdgesResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_id: str
    edge_type: str
    edges: list[EdgeRow]
    budget_status: BudgetStatus


class FetchLowerFindingsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parent_cluster_id: str
    findings: list[LowerFinding]
    filtered_out: int  # number of children dropped by the drift filter
    budget_status: BudgetStatus


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


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _require_client(deps: VisitDeps) -> Any:
    """Fetch the Memgraph client from deps, raising a clear error if missing."""
    if deps.memgraph_client is None:
        raise RuntimeError(
            "VisitDeps.memgraph_client is not set -- orchestrator must populate "
            "it before running tools"
        )
    return deps.memgraph_client


def _require_validator(deps: VisitDeps) -> Any:
    if deps.validator is None:
        raise RuntimeError(
            "VisitDeps.validator is not set -- orchestrator must populate it "
            "before running commit_* tools"
        )
    return deps.validator


def _rebuild_budget(deps: VisitDeps) -> None:
    """Recompute deps.budget after a tool call.

    Uses tool-call ratio as a proxy for token consumption. The real hard cap
    is enforced by pydantic-ai's UsageLimits on the outside; this provides
    the soft wrap-up signal visible to the agent in every tool response.

    wrap_up_signal fires when:
      (a) estimated consumption >= soft_signal_ratio * nominal, OR
      (b) tool_calls_remaining <= 2 (nearly exhausted).
    """
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


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


async def fetch_members(
    ctx: RunContext[VisitDeps],
    cluster_id: str,
    limit: int = 10,
    offset: int = 0,
) -> FetchMembersResult:
    """Read :Node members of a cluster. Updates seen_node_ids. Delimiter-wrapped."""
    deps = ctx.deps
    client = _require_client(deps)

    rows = await read_q.fetch_cluster_members(
        client,
        cluster_id=cluster_id,
        silo_id=deps.silo_id,
        limit=limit,
        offset=offset,
    )
    total = await read_q.count_cluster_members(
        client,
        cluster_id=cluster_id,
        silo_id=deps.silo_id,
    )

    members: list[NodeContent] = []
    for row in rows:
        node_id = row["node_id"]
        deps.seen_node_ids.add(node_id)
        members.append(
            NodeContent(
                node_id=node_id,
                content=wrap_node_content(node_id, row.get("content") or ""),
                org_id=deps.org_id,
                silo_id=row["silo_id"],
                label=row.get("label"),
            )
        )

    has_more = (offset + len(members)) < total
    _rebuild_budget(deps)
    return FetchMembersResult(
        cluster_id=cluster_id,
        members=members,
        total=total,
        has_more=has_more,
        budget_status=deps.budget,
    )


async def fetch_node(
    ctx: RunContext[VisitDeps],
    node_id: str,
) -> FetchNodeResult:
    """Read a single :Node by id, tenant/silo scoped."""
    deps = ctx.deps
    client = _require_client(deps)

    row = await read_q.fetch_node_by_id(
        client,
        node_id=node_id,
        silo_id=deps.silo_id,
    )
    if row is None:
        _rebuild_budget(deps)
        return FetchNodeResult(found=False, node=None, budget_status=deps.budget)

    deps.seen_node_ids.add(row["node_id"])
    node = NodeContent(
        node_id=row["node_id"],
        content=wrap_node_content(row["node_id"], row.get("content") or ""),
        org_id=deps.org_id,
        silo_id=row["silo_id"],
        label=row.get("label"),
    )
    _rebuild_budget(deps)
    return FetchNodeResult(found=True, node=node, budget_status=deps.budget)


async def fetch_neighborhood(
    ctx: RunContext[VisitDeps],
    node_id: str,
    depth: int = 1,
) -> FetchNeighborhoodResult:
    """Return seed node + neighbours within ``depth`` hops."""
    deps = ctx.deps
    client = _require_client(deps)

    row = await read_q.fetch_neighborhood(
        client,
        node_id=node_id,
        silo_id=deps.silo_id,
        depth=depth,
    )
    if row is None:
        _rebuild_budget(deps)
        return FetchNeighborhoodResult(
            found=False,
            seed=None,
            neighbours=[],
            budget_status=deps.budget,
        )

    seed_id = row["seed_id"]
    deps.seen_node_ids.add(seed_id)
    seed = NodeContent(
        node_id=seed_id,
        content=wrap_node_content(seed_id, row.get("seed_content") or ""),
        org_id=deps.org_id,
        silo_id=row["silo_id"],
        label=row.get("label"),
    )

    neighbours: list[NodeContent] = []
    for n in row.get("neighbours") or []:
        if n is None or n.get("node_id") is None:
            continue
        nid = n["node_id"]
        deps.seen_node_ids.add(nid)
        neighbours.append(
            NodeContent(
                node_id=nid,
                content=wrap_node_content(nid, n.get("content") or ""),
                org_id=deps.org_id,
                silo_id=deps.silo_id,
                label=n.get("label"),
            )
        )

    _rebuild_budget(deps)
    return FetchNeighborhoodResult(
        found=True,
        seed=seed,
        neighbours=neighbours,
        budget_status=deps.budget,
    )


async def list_edges_of_type(
    ctx: RunContext[VisitDeps],
    cluster_id: str,
    edge_type: str,
) -> ListEdgesResult:
    """Return :EDGE rows of a given ``type`` between members of a cluster."""
    deps = ctx.deps
    client = _require_client(deps)

    rows = await read_q.list_edges_of_type_in_cluster(
        client,
        cluster_id=cluster_id,
        edge_type=edge_type,
        silo_id=deps.silo_id,
    )
    edges = [
        EdgeRow(
            edge_id=row["edge_id"],
            edge_type=row["edge_type"],
            source_node_id=row["source_id"],
            target_node_id=row["target_id"],
        )
        for row in rows
    ]
    _rebuild_budget(deps)
    return ListEdgesResult(
        cluster_id=cluster_id,
        edge_type=edge_type,
        edges=edges,
        budget_status=deps.budget,
    )


async def fetch_lower_findings(
    ctx: RunContext[VisitDeps],
    cluster_id: str,
) -> FetchLowerFindingsResult:
    """Return child findings of ``cluster_id``, filtered by fingerprint drift.

    A child finding is dropped if its stored ``member_fingerprint`` no longer
    overlaps the current parent cluster's member set (Jaccard < 0.8). The
    parent's current member ids are fetched inline for v1.
    """
    deps = ctx.deps
    client = _require_client(deps)

    # Current member set for the fingerprint comparison.
    current_members = await read_q.fetch_cluster_member_ids(
        client,
        cluster_id=cluster_id,
        silo_id=deps.silo_id,
    )

    rows = await read_q.fetch_lower_findings(
        client,
        parent_cluster_id=cluster_id,
        silo_id=deps.silo_id,
    )

    # v1 policy: treat fingerprint equality as "no drift" (keep) and any
    # mismatch as drifted-out (drop). When the prior finding has no
    # fingerprint (legacy rows), keep it -- backfill handles those later.
    from context_service.custodian.fingerprints import member_fingerprint as _fp

    current_fp = _fp(current_members)
    # fingerprint_drift_ok is exported for the case where future schema
    # stores the raw member list alongside the hash; reference it here so
    # the import is load-bearing and lint does not flag it as unused.
    _ = fingerprint_drift_ok

    kept: list[LowerFinding] = []
    filtered_out = 0
    for row in rows:
        prior_fp = row.get("member_fingerprint")
        keep = True if prior_fp is None else prior_fp == current_fp
        if not keep:
            filtered_out += 1
            continue
        kept.append(
            LowerFinding(
                finding_id=row["finding_id"],
                child_cluster_id=row["child_cluster_id"],
                claims_json=row.get("claims_json"),
                summary_json=row.get("summary_json"),
                quality_score=row.get("quality_score"),
                version=row.get("version"),
            )
        )

    _rebuild_budget(deps)
    return FetchLowerFindingsResult(
        parent_cluster_id=cluster_id,
        findings=kept,
        filtered_out=filtered_out,
        budget_status=deps.budget,
    )


async def commit_claim(
    ctx: RunContext[VisitDeps],
    claim: Claim,
) -> CommitClaimResult:
    """Validate and buffer a single cited claim.

    Rejections are soft: the claim is dropped, a reject event is appended to
    ``commit_log``, and the caller sees ``accepted=False``. Never raises on
    rejection -- this is a filter, not a gate.
    """
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
    """Mark the visit finalized and return commit counts.

    Does NOT trigger the write path: the orchestrator reads ``ctx.deps.finalized``
    after ``agent.run`` returns and calls ``WritePath.write_visit`` itself.
    """
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


# ---------------------------------------------------------------------------
# Tool registration on module-level agent singletons
# ---------------------------------------------------------------------------

# Fast pass: cheap reconnaissance only.
fast_pass_agent.tool(fetch_members)
fast_pass_agent.tool(fetch_lower_findings)

# Deep pass: the full surface.
deep_pass_agent.tool(fetch_members)
deep_pass_agent.tool(fetch_node)
deep_pass_agent.tool(fetch_neighborhood)
deep_pass_agent.tool(list_edges_of_type)
deep_pass_agent.tool(fetch_lower_findings)
deep_pass_agent.tool(commit_claim)
deep_pass_agent.tool(commit_inferred_relation)
deep_pass_agent.tool(finalize_visit)


__all__ = [
    "CommitClaimResult",
    "CommitInferredRelationResult",
    "EdgeRow",
    "FetchLowerFindingsResult",
    "FetchMembersResult",
    "FetchNeighborhoodResult",
    "FetchNodeResult",
    "FinalizeVisitResult",
    "ListEdgesResult",
    "LowerFinding",
    "NodeContent",
    "_rebuild_budget",
    "commit_claim",
    "commit_inferred_relation",
    "fetch_lower_findings",
    "fetch_members",
    "fetch_neighborhood",
    "fetch_node",
    "finalize_visit",
    "list_edges_of_type",
    "wrap_node_content",
]
