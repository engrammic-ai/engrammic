"""Dataset: semantic recall quality scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.ranking import AbsentFromTopK, TopKContains

recall_dataset: Dataset[dict, list[dict], None] = Dataset(
    name="recall",
    cases=[
        Case(
            name="ml_docs_top3",
            inputs={
                "query": "machine learning neural networks gradient descent",
                "silo_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
            expected_output={
                "expected_top": [
                    "11111111-0000-0000-0000-000000000001",
                    "11111111-0000-0000-0000-000000000002",
                    "11111111-0000-0000-0000-000000000003",
                ]
            },
            evaluators=[TopKContains(k=3)],
        ),
        Case(
            name="rare_term_exact_match",
            inputs={
                "query": "NovusEdge EAG CITE schema",
                "silo_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
            expected_output={"expected_top": ["33333333-0000-0000-0000-000000000001"]},
            evaluators=[TopKContains(k=1)],
        ),
        Case(
            name="cooking_absent_from_ml_results",
            inputs={
                "query": "machine learning neural networks",
                "silo_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            },
            expected_output={"absent_id": "22222222-0000-0000-0000-000000000001"},
            evaluators=[AbsentFromTopK(k=3)],
        ),
    ],
)
