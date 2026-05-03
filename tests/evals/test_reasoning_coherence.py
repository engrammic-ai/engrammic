"""Eval: Reasoning chain coherence for context_reason."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.quality import ConclusionStored, StepsCountMatches
from tests.evals.tasks.direct import reasoning_coherence_task


@pytest.fixture
def reasoning_coherence_dataset() -> Dataset:
    return Dataset(
        name="reasoning_coherence",
        cases=[
            Case(
                name="steps_logically_connected",
                inputs={
                    "steps": [
                        {
                            "step": 1,
                            "reasoning": "All mammals are warm-blooded.",
                            "confidence": 0.99,
                        },
                        {
                            "step": 2,
                            "reasoning": "Whales are mammals.",
                            "confidence": 0.99,
                        },
                        {
                            "step": 3,
                            "reasoning": "Therefore whales are warm-blooded.",
                            "confidence": 0.98,
                        },
                    ],
                    "conclusion": "Whales are warm-blooded.",
                    "crystallizations": None,
                },
                expected_output={"steps_count": 3},
                evaluators=[StepsCountMatches(expected=3), ConclusionStored()],
            ),
            Case(
                name="conclusion_follows_from_steps",
                inputs={
                    "steps": [
                        {
                            "step": 1,
                            "reasoning": "context-service uses Memgraph for graph storage.",
                            "confidence": 0.95,
                        },
                        {
                            "step": 2,
                            "reasoning": "Memgraph supports Cypher queries.",
                            "confidence": 0.95,
                        },
                    ],
                    "conclusion": "context-service supports Cypher for graph traversal.",
                    "crystallizations": None,
                },
                expected_output={"steps_count": 2},
                evaluators=[StepsCountMatches(expected=2), ConclusionStored()],
            ),
            Case(
                name="crystallizations_produce_knowledge_nodes",
                inputs={
                    "steps": [
                        {
                            "step": 1,
                            "reasoning": "The EAG paradigm defines four cognitive layers.",
                            "confidence": 0.9,
                        },
                        {
                            "step": 2,
                            "reasoning": "Intelligence is the highest EAG layer.",
                            "confidence": 0.9,
                        },
                    ],
                    "conclusion": "Intelligence layer is the apex of EAG cognition.",
                    "crystallizations": [
                        {
                            "claim": "EAG has four layers: Memory, Knowledge, Wisdom, Intelligence.",
                            "confidence": 0.9,
                        }
                    ],
                },
                expected_output={"steps_count": 2, "crystallizations_count": 1},
                evaluators=[StepsCountMatches(expected=2), ConclusionStored()],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_reasoning_coherence_quality(
    reasoning_coherence_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
) -> None:
    """Verify reasoning chains are stored with correct step counts and conclusions."""

    async def task(inputs: dict) -> dict:
        return await reasoning_coherence_task(inputs, context_service, scope_context)

    report = await reasoning_coherence_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        assert output.get("chain_id"), f"Case {case_result.name}: chain_id missing"
        expected_steps = case_result.expected_output.get("steps_count")
        if expected_steps is not None:
            assert output.get("steps_count") == expected_steps, (
                f"Case {case_result.name}: steps_count {output.get('steps_count')} "
                f"!= {expected_steps}"
            )
