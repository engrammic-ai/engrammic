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

    assert verdict == "PASS", f"Claim coherence: {verdict}"


EXTRACTION_PROMPT = """You are evaluating whether an extracted claim accurately represents the source content.

Source content:
{source}

Extracted claim:
{claim}

The extraction is correct if:
1. The claim is factually present in or directly implied by the source
2. The claim does not add information not in the source
3. The claim does not distort or misrepresent the source

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_extraction_quality_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge if extracted claims match source content."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    source_content = (
        "The Eiffel Tower was completed in 1889 for the World's Fair. "
        "It stands 330 meters tall and was designed by Gustave Eiffel."
    )
    extracted_claim = "The Eiffel Tower was completed in 1889 and is 330 meters tall."

    source_node = await context_service.remember(
        scope=scope_context,
        content=source_content,
        content_type="text",
    )

    await context_service.assert_claim(
        scope=scope_context,
        claim=extracted_claim,
        evidence=[f"node:{source_node.id}"],
        source_type="document",
        confidence=0.9,
    )

    llm = get_llm_provider(llm_provider)
    prompt = EXTRACTION_PROMPT.format(source=source_content, claim=extracted_claim)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"Extraction quality: {verdict}"


RELEVANCE_PROMPT = """You are evaluating whether search results are relevant to a query.

Query: {query}

Results:
{results}

The results are relevant if:
1. They contain information that helps answer or relate to the query
2. The connection between results and query is clear and direct
3. At least one result is highly relevant (not just tangentially related)

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_relevance_judgment_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge if query results are actually relevant."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    docs = [
        "Redis is an in-memory data structure store used as a database and cache.",
        "PostgreSQL is a relational database with strong ACID compliance.",
        "MongoDB is a document-oriented NoSQL database.",
    ]
    for doc in docs:
        await context_service.remember(
            scope=scope_context, content=doc, content_type="text"
        )

    query = "in-memory caching database"
    results = await context_service.query(scope_context, query, top_k=3)

    results_text = "\n".join(f"- {r.content[:100]}" for r in results if r.content)

    llm = get_llm_provider(llm_provider)
    prompt = RELEVANCE_PROMPT.format(query=query, results=results_text)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"Relevance judgment: {verdict}"


CONTRADICTION_PROMPT = """You are evaluating whether two claims contradict each other.

Claim A: {claim_a}
Claim B: {claim_b}

Claims contradict if:
1. They make assertions that cannot both be true
2. One directly negates or conflicts with the other
3. Accepting one as true requires rejecting the other

Do these claims contradict? Respond with exactly one word: YES or NO"""


@pytest.mark.evals
@pytest.mark.integration
async def test_contradiction_detection_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to detect contradicting claims."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    claim_a = "Python is a statically typed programming language."
    claim_b = "Python is a dynamically typed programming language."

    for claim in [claim_a, claim_b]:
        await context_service.assert_claim(
            scope=scope_context,
            claim=claim,
            evidence=[],
            source_type="document",
            confidence=0.8,
        )

    llm = get_llm_provider(llm_provider)
    prompt = CONTRADICTION_PROMPT.format(claim_a=claim_a, claim_b=claim_b)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "YES", f"Should detect contradiction: {verdict}"


EVIDENCE_SUFFICIENCY_PROMPT = """You are evaluating whether evidence sufficiently supports a claim.

Claim: {claim}

Evidence:
{evidence}

The evidence is sufficient if:
1. It directly supports the claim's core assertion
2. There are no obvious gaps that would require additional proof
3. A reasonable person would accept the claim based on this evidence

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_evidence_sufficiency_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge if evidence supports a claim."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    evidence_content = (
        "A 2023 study by MIT researchers found that code review catches "
        "an average of 65% of bugs before they reach production."
    )
    claim = "Code review is effective at catching bugs before production."

    evidence_node = await context_service.remember(
        scope=scope_context,
        content=evidence_content,
        content_type="text",
    )

    await context_service.assert_claim(
        scope=scope_context,
        claim=claim,
        evidence=[f"node:{evidence_node.id}"],
        source_type="document",
        confidence=0.9,
    )

    llm = get_llm_provider(llm_provider)
    prompt = EVIDENCE_SUFFICIENCY_PROMPT.format(claim=claim, evidence=evidence_content)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"Evidence sufficiency: {verdict}"


SUMMARY_FIDELITY_PROMPT = """You are evaluating whether a summary accurately captures key points without hallucination.

Original content:
{original}

Summary:
{summary}

The summary is faithful if:
1. All facts in the summary are present in the original
2. Key points from the original are captured
3. No information is fabricated or distorted

Respond with exactly one word: PASS or FAIL"""


@pytest.mark.evals
@pytest.mark.integration
async def test_summary_fidelity_llm_judge(
    with_llm: bool,
    llm_provider: str,
    context_service,
    scope_context: ScopeContext,
    cleanup_silo,
) -> None:
    """Use LLM to judge if summaries are faithful to original content."""
    if not with_llm:
        pytest.skip("--with-llm not set")

    original = (
        "Kubernetes is an open-source container orchestration platform. "
        "It was originally developed by Google and released in 2014. "
        "Kubernetes automates deployment, scaling, and management of containerized applications. "
        "It uses a declarative configuration model and supports multiple cloud providers."
    )
    summary = (
        "Kubernetes is a Google-developed open-source platform from 2014 "
        "that automates container deployment and scaling across cloud providers."
    )

    await context_service.remember(
        scope=scope_context,
        content=original,
        content_type="text",
        metadata={"summary": summary},
    )

    llm = get_llm_provider(llm_provider)
    prompt = SUMMARY_FIDELITY_PROMPT.format(original=original, summary=summary)
    messages = [{"role": "user", "content": prompt}]

    judgment, _usage = await llm.complete(messages, max_tokens=10)
    verdict = judgment.strip().upper()

    assert verdict == "PASS", f"Summary fidelity: {verdict}"
