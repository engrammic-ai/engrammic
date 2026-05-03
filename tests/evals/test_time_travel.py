"""Eval: Time-travel precision for temporal_query (context_history / as_of)."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.tasks.direct import time_travel_task


@pytest.fixture
def time_travel_dataset() -> Dataset:
    return Dataset(
        name="time_travel",
        cases=[
            Case(
                name="as_of_future_returns_both_nodes",
                inputs={
                    "content_before": "Redis is an in-memory key-value store.",
                    "content_after": "Qdrant is a vector similarity search engine.",
                    "query": "database storage",
                    "as_of_before_update": False,
                },
                # Query with as_of in the future should see both nodes.
                expected_output={"min_results": 2},
                evaluators=[],
            ),
            Case(
                name="as_of_past_returns_no_nodes",
                inputs={
                    "content_before": "Dagster is a data orchestration platform.",
                    "content_after": "FastMCP exposes tools over the Model Context Protocol.",
                    "query": "orchestration platform",
                    "as_of_before_update": True,
                },
                # Query with as_of 10 minutes in the past should not see nodes
                # created just now (valid_from is set at write time).
                expected_output={"max_results": 0},
                evaluators=[],
            ),
            Case(
                name="updates_visible_after_timestamp",
                inputs={
                    "content_before": "structlog provides structured logging for Python.",
                    "content_after": "pydantic-evals is used for AI evaluation datasets.",
                    "query": "python library",
                    "as_of_before_update": False,
                },
                expected_output={"before_id_found": True, "after_id_found": True},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_time_travel_precision(
    time_travel_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
) -> None:
    """Verify temporal_query returns correct historical state at various as_of points."""

    async def task(inputs: dict) -> dict:
        return await time_travel_task(inputs, context_service, scope_context)

    report = await time_travel_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        expected = case_result.expected_output

        if "min_results" in expected:
            assert output["results_count"] >= expected["min_results"], (
                f"Case {case_result.name}: expected >= {expected['min_results']} results, "
                f"got {output['results_count']}"
            )

        if "max_results" in expected:
            assert output["results_count"] <= expected["max_results"], (
                f"Case {case_result.name}: expected <= {expected['max_results']} results, "
                f"got {output['results_count']}"
            )

        if expected.get("before_id_found") is not None:
            assert output["before_id_found"] == expected["before_id_found"], (
                f"Case {case_result.name}: before_id_found mismatch"
            )

        if expected.get("after_id_found") is not None:
            assert output["after_id_found"] == expected["after_id_found"], (
                f"Case {case_result.name}: after_id_found mismatch"
            )
