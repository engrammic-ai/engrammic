"""Eval: Cross-layer graph traversal scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.tasks.direct import cross_layer_task


@pytest.fixture
def cross_layer_dataset() -> Dataset:
    return Dataset(
        name="cross_layer",
        cases=[
            Case(
                name="memory_to_claim_linked",
                inputs={
                    "memory_content": "Alice is a software engineer at NovusEdge.",
                    "claim_content": "Alice works in software engineering.",
                },
                expected_output={},
                evaluators=[],
            ),
            Case(
                name="claim_references_memory_in_graph",
                inputs={
                    "memory_content": "The context-service uses Memgraph for graph storage.",
                    "claim_content": "Memgraph is the primary graph database for context-service.",
                },
                expected_output={},
                evaluators=[],
            ),
            Case(
                name="depth2_traversal_reaches_memory",
                inputs={
                    "memory_content": "EAG stands for Epistemic Augmented Generation.",
                    "claim_content": "The EAG paradigm succeeds the CAG architecture.",
                },
                expected_output={},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_cross_layer_quality(
    cross_layer_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run cross-layer dataset and verify graph linkage."""

    async def task(inputs: dict) -> dict:
        return await cross_layer_task(inputs, context_service, scope_context)

    report = await cross_layer_dataset.evaluate(task)
    report.print()

    for case_result in report.case_results:
        output = case_result.output
        assert output is not None, f"Case {case_result.case.name}: no output"
        assert output.get("linked"), (
            f"Case {case_result.case.name}: memory node not linked to claim in graph"
        )
