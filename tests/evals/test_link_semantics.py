"""Eval: Link relationship semantics for context_link."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.quality import SourceReachableReverse, TargetReachable
from tests.evals.tasks.direct import link_semantics_task


@pytest.fixture
def link_semantics_dataset() -> Dataset:
    return Dataset(
        name="link_semantics",
        cases=[
            Case(
                name="supports_link_target_reachable",
                inputs={
                    "source_content": "The EAG knowledge layer stores verified claims.",
                    "target_content": "Claims graduate to Facts via R1/R2 consensus.",
                    "relationship": "SUPPORTS",
                    "traversal_depth": 2,
                },
                expected_output={},
                evaluators=[TargetReachable(), SourceReachableReverse()],
            ),
            Case(
                name="contradicts_link_still_traversable",
                inputs={
                    "source_content": "High confidence implies a claim should be promoted.",
                    "target_content": "Confidence alone is insufficient for Fact promotion.",
                    "relationship": "CONTRADICTS",
                    "traversal_depth": 2,
                },
                expected_output={},
                evaluators=[TargetReachable()],
            ),
            Case(
                name="transitive_references_reachable",
                inputs={
                    "source_content": "Qdrant stores vector embeddings for semantic search.",
                    "target_content": "Semantic search enables context_query to rank by relevance.",
                    "relationship": "REFERENCES",
                    "traversal_depth": 2,
                },
                expected_output={},
                evaluators=[TargetReachable(), SourceReachableReverse()],
            ),
            Case(
                name="bidirectional_traversal_derived_from",
                inputs={
                    "source_content": "The Leiden algorithm partitions graphs into clusters.",
                    "target_content": "Clustering summaries are stored in the Wisdom layer.",
                    "relationship": "DERIVED_FROM",
                    "traversal_depth": 1,
                },
                expected_output={},
                evaluators=[TargetReachable(), SourceReachableReverse()],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_link_semantics_quality(
    link_semantics_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
) -> None:
    """Verify typed links are created and traversable in both directions."""

    async def task(inputs: dict) -> dict:
        return await link_semantics_task(inputs, context_service, scope_context)

    report = await link_semantics_dataset.evaluate(task)
    report.print()

    for case_result in report.cases:
        output = case_result.output
        assert output is not None, f"Case {case_result.name}: no output"
        assert output.get("edge_id"), (
            f"Case {case_result.name}: edge_id missing -- link was not created"
        )
        assert output.get("target_reachable"), (
            f"Case {case_result.name}: target node not reachable from source via graph traversal"
        )
