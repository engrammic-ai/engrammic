"""Eval: Provenance chain integrity scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.tasks.direct import provenance_task


@pytest.fixture
def provenance_dataset() -> Dataset:
    return Dataset(
        name="provenance",
        cases=[
            Case(
                name="single_hop_chain",
                inputs={
                    "doc_content": "Berlin is located in northeastern Germany.",
                    "claim_content": "Berlin is the capital of Germany.",
                },
                expected_output={},
                evaluators=[],
            ),
            Case(
                name="source_document_in_chain",
                inputs={
                    "doc_content": "Python was created by Guido van Rossum in 1991.",
                    "claim_content": "Python is a programming language created in the early 1990s.",
                },
                expected_output={},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_provenance_quality(
    provenance_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run provenance dataset and verify chain integrity."""

    async def task(inputs: dict) -> dict:
        return await provenance_task(inputs, context_service, scope_context)

    report = await provenance_dataset.evaluate(task)
    report.print()

    for case_result in report.case_results:
        output = case_result.output
        assert output is not None, f"Case {case_result.case.name}: no output"
        assert output.get("chain"), f"Case {case_result.case.name}: empty chain"
        assert output.get("root_id") == output.get("expected_root"), (
            f"Case {case_result.case.name}: root mismatch - "
            f"expected {output.get('expected_root')}, got {output.get('root_id')}"
        )
