"""LLM agent task functions for evals.

These functions use a pydantic-ai Agent with MCP tools registered,
allowing the LLM to decide which tools to call for each scenario.
Used with --with-llm flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, RunContext

if TYPE_CHECKING:
    from context_service.services.context import ContextService
    from context_service.services.models import ScopeContext


@dataclass
class AgentDeps:
    """Dependencies injected into agent tool calls."""

    context_service: ContextService
    scope: ScopeContext


def create_eval_agent(model: str = "anthropic:claude-sonnet-4-6") -> Agent[AgentDeps, str]:
    """Create a pydantic-ai Agent with context tools registered."""
    agent: Agent[AgentDeps, str] = Agent(
        model,
        system_prompt=(
            "You are an agent with access to a context management system. "
            "Use the provided tools to complete tasks. "
            "Always use the most appropriate tool for the task at hand."
        ),
        deps_type=AgentDeps,
    )

    @agent.tool
    async def remember(
        ctx: RunContext[AgentDeps],
        content: str,
        content_type: str = "text",
    ) -> str:
        """Store content in memory layer."""
        node = await ctx.deps.context_service.remember(
            scope=ctx.deps.scope,
            content=content,
            content_type=content_type,
        )
        return f"Stored node: {node.id}"

    @agent.tool
    async def query(
        ctx: RunContext[AgentDeps],
        query_text: str,
        top_k: int = 5,
    ) -> str:
        """Search for relevant content."""
        results = await ctx.deps.context_service.query(
            ctx.deps.scope,
            query_text,
            top_k=top_k,
        )
        if not results:
            return "No results found."
        return "\n".join(
            f"- {r.content[:100]}... (score: {r.relevance_score:.2f})" for r in results
        )

    @agent.tool
    async def assert_claim(
        ctx: RunContext[AgentDeps],
        claim: str,
        evidence: list[str],
        confidence: float = 0.8,
    ) -> str:
        """Assert a claim with evidence."""
        node = await ctx.deps.context_service.assert_claim(
            scope=ctx.deps.scope,
            claim=claim,
            evidence=evidence,
            source_type="document",
            confidence=confidence,
        )
        return f"Asserted claim: {node.id}"

    @agent.tool
    async def reflect(
        ctx: RunContext[AgentDeps],
        about_node_id: str,
        observation: str,
        observation_type: str = "insight",
    ) -> str:
        """Add a meta-observation about a node."""
        await ctx.deps.context_service.reflect(
            scope=ctx.deps.scope,
            observation=observation,
            observation_type=observation_type,
            about=[about_node_id],
            agent_id="eval-agent",
        )
        return f"Added reflection about {about_node_id}"

    return agent


async def agent_recall_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
    model: str = "anthropic:claude-sonnet-4-6",
) -> list[dict[str, Any]]:
    """Agent-driven recall task.

    The agent decides how to store docs and query.
    """
    agent = create_eval_agent(model)
    deps = AgentDeps(context_service=context_service, scope=scope)

    corpus_desc = "\n".join(f"- {d['content']}" for d in inputs["corpus"])
    prompt = f"""Store these documents in memory, then search for documents about: "{inputs["query"]}"

Documents to store:
{corpus_desc}

After storing, run a query and report what you found."""

    await agent.run(prompt, deps=deps)

    query_results = await context_service.query(scope, inputs["query"], top_k=10)
    return [
        {
            "id": str(r.node_id),
            "score": r.relevance_score,
        }
        for r in query_results
    ]


async def agent_claim_task(
    inputs: dict[str, Any],
    context_service: ContextService,
    scope: ScopeContext,
    model: str = "anthropic:claude-sonnet-4-6",
) -> dict[str, Any]:
    """Agent-driven claim assertion task."""
    agent = create_eval_agent(model)
    deps = AgentDeps(context_service=context_service, scope=scope)

    prompt = f"""Assert the following claim with high confidence:
"{inputs["claim"]}"

Evidence: {inputs.get("evidence", ["general knowledge"])}"""

    await agent.run(prompt, deps=deps)

    results = await context_service.query(scope, inputs["claim"], top_k=1)
    if results:
        return {
            "id": str(results[0].node_id),
            "promoted": False,
            "fact_id": None,
        }
    return {"id": None, "promoted": False, "fact_id": None}
