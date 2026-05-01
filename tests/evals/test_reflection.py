"""Eval: Reflection round-trip scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.tasks.direct import reflection_task


@pytest.fixture
def reflection_dataset() -> Dataset:
    return Dataset(
        name="reflection",
        cases=[
            Case(
                name="store_and_retrieve_reflection",
                inputs={
                    "content": "The user prefers concise responses.",
                    "observation": "This preference has been consistent across multiple sessions.",
                    "observation_type": "pattern",
                },
                expected_output={"reflection_count": 1},
                evaluators=[],
            ),
            Case(
                name="multiple_reflections_on_same_node",
                inputs={
                    "content": "User asked about machine learning.",
                    "observation": "User shows interest in ML fundamentals.",
                    "observation_type": "insight",
                },
                expected_output={"reflection_count": 1},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_reflection_quality(
    reflection_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run reflection dataset and verify round-trip."""

    async def task(inputs: dict) -> dict:
        return await reflection_task(inputs, context_service, scope_context)

    report = await reflection_dataset.evaluate(task)
    report.print()

    for case_result in report.case_results:
        output = case_result.output
        assert output is not None, f"Case {case_result.case.name}: no output"
        reflections = output.get("reflections", [])
        assert len(reflections) >= 1, (
            f"Case {case_result.case.name}: expected at least 1 reflection, got {len(reflections)}"
        )
        assert reflections[0].get("observation"), (
            f"Case {case_result.case.name}: reflection missing observation content"
        )
