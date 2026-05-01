"""Eval: Recall quality scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.ranking import AbsentFromTopK, TopKContains
from tests.evals.tasks.direct import recall_task

ML_CORPUS = [
    {"id": "ml-1", "content": "Neural networks use gradient descent to optimize model weights."},
    {
        "id": "ml-2",
        "content": "Transformer architectures rely on self-attention for sequence modeling.",
    },
    {
        "id": "ml-3",
        "content": "Supervised machine learning maps labeled inputs to predicted outputs.",
    },
]

COOKING_CORPUS = [
    {"id": "cook-1", "content": "Sautee onions in olive oil until translucent."},
    {"id": "cook-2", "content": "Bake the bread at 375 degrees for 45 minutes."},
]

RARE_TERM_CORPUS = [
    {"id": "rare-1", "content": "The NovusEdge EAG CITE schema defines four cognitive layers."},
]


@pytest.fixture
def recall_dataset() -> Dataset:
    return Dataset(
        name="recall",
        cases=[
            Case(
                name="ml_query_ranks_ml_docs",
                inputs={
                    "corpus": ML_CORPUS + COOKING_CORPUS,
                    "query": "machine learning neural networks",
                },
                expected_output={"expected_top": ["ml-1", "ml-2", "ml-3"]},
                evaluators=[TopKContains(k=3)],
            ),
            Case(
                name="cooking_absent_from_ml_query",
                inputs={
                    "corpus": ML_CORPUS + COOKING_CORPUS,
                    "query": "machine learning optimization",
                },
                expected_output={"absent_id": "cook-1"},
                evaluators=[AbsentFromTopK(k=3)],
            ),
            Case(
                name="rare_term_exact_match",
                inputs={
                    "corpus": ML_CORPUS + RARE_TERM_CORPUS,
                    "query": "NovusEdge EAG CITE",
                },
                expected_output={"expected_top": ["rare-1"]},
                evaluators=[TopKContains(k=1)],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_recall_quality(
    recall_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run recall dataset and verify ranking quality."""

    async def task(inputs: dict) -> list[dict]:
        return await recall_task(inputs, context_service, scope_context)

    report = await recall_dataset.evaluate(task)
    report.print()

    # Quality evals print results - no hard assertions for now
    # Failures are expected as we tune the system
