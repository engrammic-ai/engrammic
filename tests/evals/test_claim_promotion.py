"""Eval: Claim promotion scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.tasks.direct import claim_promotion_task


@pytest.fixture
def claim_promotion_dataset() -> Dataset:
    return Dataset(
        name="claim_promotion",
        cases=[
            Case(
                name="authoritative_high_confidence_promotes",
                inputs={
                    "claim": "The capital of France is Paris",
                    "evidence": ["node:ref-1"],
                    "confidence": 0.9,
                    "source_tier": "authoritative",
                },
                expected_output={"promoted": True},
                evaluators=[],
            ),
            Case(
                name="low_confidence_not_promoted",
                inputs={
                    "claim": "The sky might be purple sometimes",
                    "evidence": [],
                    "confidence": 0.4,
                    "source_tier": "standard",
                },
                expected_output={"promoted": False},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_claim_promotion_quality(
    claim_promotion_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run claim promotion dataset and verify promotion logic."""

    async def task(inputs: dict) -> dict:
        return await claim_promotion_task(inputs, context_service, scope_context)

    report = await claim_promotion_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        expected_promoted = case_result.expected_output.get("promoted")
        actual_promoted = case_result.output.get("promoted") if case_result.output else False
        assert actual_promoted == expected_promoted, (
            f"Case {case_result.name}: expected promoted={expected_promoted}, "
            f"got {actual_promoted}"
        )
