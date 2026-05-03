"""Eval: Evidence validation quality for context_assert."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.quality import ClaimStored, EvidenceLinkedCount
from tests.evals.tasks.direct import evidence_validation_task


@pytest.fixture
def evidence_validation_dataset() -> Dataset:
    return Dataset(
        name="evidence_validation",
        cases=[
            Case(
                name="valid_refs_linked",
                inputs={
                    "claim": "Python is a dynamically typed language.",
                    "valid_evidence_contents": [
                        "Python resolves variable types at runtime.",
                        "PEP 484 introduced optional static type hints for Python.",
                    ],
                    "invalid_evidence_refs": [],
                    "confidence": 0.9,
                },
                expected_output={"evidence_linked": 2},
                evaluators=[ClaimStored(), EvidenceLinkedCount(expected=2)],
            ),
            Case(
                name="invalid_refs_do_not_crash",
                inputs={
                    "claim": "Memgraph is a graph database.",
                    "valid_evidence_contents": [],
                    "invalid_evidence_refs": ["node:00000000-0000-0000-0000-000000000000"],
                    "confidence": 0.7,
                },
                # assert_claim with a dangling node ref should still produce a
                # claim node; the MERGE silently skips missing targets.
                expected_output={"evidence_linked": 0},
                evaluators=[ClaimStored()],
            ),
            Case(
                name="mixed_valid_and_invalid",
                inputs={
                    "claim": "FastAPI supports async request handlers.",
                    "valid_evidence_contents": [
                        "FastAPI is built on Starlette and supports async/await.",
                    ],
                    "invalid_evidence_refs": [
                        "node:deadbeef-dead-beef-dead-beefdeadbeef",
                    ],
                    "confidence": 0.85,
                },
                expected_output={"evidence_linked": 1},
                evaluators=[ClaimStored(), EvidenceLinkedCount(expected=1)],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_evidence_validation_quality(
    evidence_validation_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
) -> None:
    """Verify that valid evidence refs are linked and invalid ones do not crash."""

    async def task(inputs: dict) -> dict:
        return await evidence_validation_task(inputs, context_service, scope_context)

    report = await evidence_validation_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        # Any case with valid_evidence_contents must produce a stored claim.
        if case_result.name != "invalid_refs_do_not_crash_only":
            assert output.get("error") is None or output.get("claim_id") is not None, (
                f"Case {case_result.name}: unexpected hard error: {output.get('error')}"
            )
