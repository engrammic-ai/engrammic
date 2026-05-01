"""Eval: Silo isolation boundary scenarios."""

from __future__ import annotations

import uuid

import pytest
from pydantic_evals import Case, Dataset

from context_service.services.models import ScopeContext
from tests.evals.tasks.direct import silo_isolation_task


@pytest.fixture
def silo_isolation_dataset() -> Dataset:
    return Dataset(
        name="silo_isolation",
        cases=[
            Case(
                name="query_does_not_cross_silos",
                inputs={
                    "content": "Confidential strategy document for silo Alpha only.",
                    "query": "confidential strategy silo Alpha",
                },
                expected_output={"found": False},
                evaluators=[],
            ),
            Case(
                name="knowledge_graph_does_not_leak",
                inputs={
                    "content": "Internal API key rotation policy for team Alpha.",
                    "query": "API key rotation policy",
                },
                expected_output={"found": False},
                evaluators=[],
            ),
            Case(
                name="memory_scoped_to_writing_silo",
                inputs={
                    "content": "Project Phoenix roadmap is classified to silo Alpha.",
                    "query": "Project Phoenix roadmap classified",
                },
                expected_output={"found": False},
                evaluators=[],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_silo_isolation_quality(
    silo_isolation_dataset: Dataset,
    context_service,
    unique_org_id: str,
    cleanup_silo,
):
    """Run silo isolation dataset and verify data does not leak across silos."""
    silo_a = ScopeContext(org_id=unique_org_id, silo_id=uuid.uuid4())
    silo_b = ScopeContext(org_id=unique_org_id, silo_id=uuid.uuid4())

    async def task(inputs: dict) -> dict:
        return await silo_isolation_task(inputs, context_service, silo_a, silo_b)

    report = await silo_isolation_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        assert not output.get("found"), (
            f"Case {case_result.name}: data from silo A leaked into silo B query"
        )
