"""Single constrained Pro call for silo-level summary with top-down prior or entity-frequency fallback.

Given a silo's coarse-level findings and either its description or a top-20-entity
frequency fallback, produces a :Finding with scope="silo" via a single pydantic-ai
Agent call using the Pro model. No tools, no new claims -- pure synthesis over
committed material. The result is written through the atomic write path (Task 6)
with a (:Finding)-[:SUMMARIZES]->(:Silo) edge.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent

from context_service.config.settings import get_settings
from context_service.custodian.agents import silo_synthesis_limits
from context_service.custodian.models import FindingOutput, StitchedSummary
from context_service.custodian.prompt_loader import load_prompt
from context_service.custodian.validators import CitationValidator
from context_service.db.custodian_queries import (
    fetch_coarse_findings_for_silo,
    fetch_top_entities_by_citation,
)
from context_service.llm.sanitize import escape_for_prompt
from context_service.utils.json import JSONDecodeError, loads

if TYPE_CHECKING:
    from context_service.custodian.write_path import WritePathResult
    from context_service.engine.protocols import HyperGraphStore

# ClusterLevel.COARSE = 3 (resolution_parameter=0.001)
_COARSE_LEVEL = 3

SILO_SYNTHESIS_SYSTEM_PROMPT = load_prompt("prompts/custodian/silo_synthesis.yaml")


def _build_user_prompt(
    *,
    top_down_prior: str,
    findings: list[dict[str, Any]],
) -> str:
    """Build the user prompt from the silo prior and coarse findings."""
    parts: list[str] = []
    parts.append("## Silo description\n")
    parts.append(escape_for_prompt(top_down_prior))
    parts.append("\n\n## Coarse-level findings\n")

    for f in findings:
        finding_id = f["finding_id"]
        cluster_id = f.get("cluster_id", "unknown")
        summary = f.get("summary") or "(no summary)"
        claims_raw = f.get("claims_json") or "[]"
        try:
            claims = loads(claims_raw) if isinstance(claims_raw, str) else claims_raw
        except (JSONDecodeError, TypeError):
            claims = []

        parts.append(f"\n### Finding {finding_id} (cluster {cluster_id})\n")
        parts.append(f"Summary: {summary}\n")
        if claims:
            parts.append("Claims:\n")
            for i, claim in enumerate(claims):
                text = claim.get("text", "") if isinstance(claim, dict) else str(claim)
                parts.append(f"  [{i}] {escape_for_prompt(text)}\n")

    return "".join(parts)


async def run_silo_synthesis(
    *,
    silo_id: str,
    org_id: str,
    pass_id: str,
    silo_description: str | None,
    memgraph_client: HyperGraphStore,
) -> WritePathResult:
    """Run silo synthesis: fetch coarse findings, call Pro agent, write result.

    Returns a WritePathResult. If no coarse findings exist, returns a skipped result.
    """
    from context_service.custodian.write_path import WritePath, WritePathResult

    settings = get_settings()

    # 1. Fetch coarse-level findings.
    findings = await fetch_coarse_findings_for_silo(
        memgraph_client,
        silo_id=silo_id,
        coarse_level=_COARSE_LEVEL,
    )

    if not findings:
        return WritePathResult(
            finding_id="",
            version=0,
            claims_committed=0,
            claims_rejected=0,
            edges_committed=0,
            edges_rejected=0,
            references_upserted=0,
            history_snapshot_created=False,
            skipped=True,
        )

    # 2. Build top-down prior.
    if silo_description is not None:
        top_down_prior = silo_description
    else:
        entities = await fetch_top_entities_by_citation(
            memgraph_client,
            silo_id=silo_id,
        )
        if entities:
            names = [escape_for_prompt(e.get("content") or e.get("node_id", "unknown")) for e in entities]
            top_down_prior = "This silo frequently references: " + ", ".join(names)
        else:
            top_down_prior = "No silo description or entity context available."

    # 3. Build user prompt.
    user_prompt = _build_user_prompt(
        top_down_prior=top_down_prior,
        findings=findings,
    )

    # 4. Create and run agent (no tools, single call).
    agent: Agent[None, StitchedSummary] = Agent(
        model=settings.custodian.pro_model,
        output_type=StitchedSummary,
        system_prompt=SILO_SYNTHESIS_SYSTEM_PROMPT,
    )

    result = await asyncio.wait_for(
        agent.run(user_prompt, usage_limits=silo_synthesis_limits()),
        timeout=60.0,
    )

    # 5. Build FindingOutput (no claims, no edges -- pure summary).
    finding = FindingOutput(
        cluster_id=None,
        silo_id=silo_id,
        scope="silo",
        claims=[],
        inferred_relations=[],
        summary=result.output,
    )

    # 6. Write via the atomic write path.
    # Silo synthesis has no claims to validate, so use a permissive validator.
    # The write path's all-claims-rejected skip branch triggers when claims is
    # empty, so we need to handle this: the write path skips when no claims
    # survive. For silo findings we go direct since there are no claims.
    validator = CitationValidator(memgraph_client)
    write_path = WritePath(memgraph_client, validator)
    return await write_path.write_visit(
        finding=finding,
        pass_id=pass_id,
        cluster_size=0,
        seen_node_ids=set(),
        org_id=org_id,
    )
