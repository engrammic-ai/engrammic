"""Eval: LLM-as-judge quality assessment.

These tests use a live LLM to evaluate semantic quality of system outputs.
Skipped unless --with-llm is passed.
"""

from __future__ import annotations

import pytest

from context_service.services.models import ScopeContext


def get_llm_provider(provider: str):
    """Factory for LLM provider based on provider flag."""
    if provider == "anthropic":
        from context_service.llm.anthropic import AnthropicProvider

        return AnthropicProvider.from_settings()
    elif provider == "openai":
        from context_service.llm.openai import OpenAIProvider

        return OpenAIProvider.from_settings()
    elif provider == "gemini":
        from context_service.llm.gemini import GeminiProvider

        return GeminiProvider.from_settings()
    elif provider == "vertex":
        from context_service.llm.vertex_gemini import VertexGeminiProvider

        return VertexGeminiProvider.from_settings()
    else:
        raise ValueError(f"Unknown provider: {provider}")


JUDGE_PROMPT = """You are evaluating the quality of a reasoning chain stored in a knowledge system.

Given the input steps and conclusion, assess whether:
1. The steps follow logically from each other
2. The conclusion follows from the steps
3. The reasoning is coherent and well-structured

Reasoning chain:
{steps}

Conclusion: {conclusion}

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_reasoning_chain_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge quality of a stored reasoning chain."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    from context_service.models.mcp import ReasoningStep

    steps = [
        ReasoningStep(step=1, reasoning="All mammals are warm-blooded.", confidence=0.95),
        ReasoningStep(step=2, reasoning="Whales are mammals.", confidence=0.95),
        ReasoningStep(step=3, reasoning="Therefore, whales are warm-blooded.", confidence=0.90),
    ]
    conclusion = "Whales are warm-blooded because they are mammals."

    result = await context_service.reason(
        silo_id=str(scope_context.silo_id),
        steps=steps,
        conclusion=conclusion,
        session_id="llm-judge-eval",
        agent_id="eval",
    )

    assert result.chain_id, "Reasoning chain was not stored"

    llm = get_llm_provider(llm_provider)
    steps_text = "\n".join(f"Step {s.step}: {s.reasoning}" for s in steps)
    prompt = JUDGE_PROMPT.format(steps=steps_text, conclusion=conclusion)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"LLM judge verdict: {verdict}"


COHERENCE_PROMPT = """You are evaluating whether a claim is coherent and well-formed.

Claim: {claim}
Evidence summary: {evidence}

A claim is coherent if:
1. It makes a clear, falsifiable assertion
2. The evidence (if any) is relevant to the claim
3. The language is precise and unambiguous

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_claim_coherence_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge coherence of an asserted claim."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    evidence_node = await context_service.remember(
        scope=scope_context,
        content="Python 3.12 was released in October 2023 with improved error messages.",
        content_type="text",
    )

    claim_node = await context_service.assert_claim(
        scope=scope_context,
        claim="Python 3.12 includes enhanced error messages for debugging.",
        evidence=[f"node:{evidence_node.id}"],
        source_type="document",
        confidence=0.9,
    )

    assert claim_node.id, "Claim was not stored"

    llm = get_llm_provider(llm_provider)
    prompt = COHERENCE_PROMPT.format(
        claim="Python 3.12 includes enhanced error messages for debugging.",
        evidence="Python 3.12 was released in October 2023 with improved error messages.",
    )
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"LLM judge verdict: {verdict}"
