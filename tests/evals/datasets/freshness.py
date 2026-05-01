"""Dataset: freshness signal ranking scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.ranking import RankHigherThan

freshness_dataset: Dataset[dict, dict, None] = Dataset(
    name="freshness",
    cases=[
        Case(
            name="fresh_outranks_stale_equal_score",
            inputs={
                "query": "context retrieval knowledge",
                "fresh_id": "55555555-0000-0000-0000-000000000001",
                "stale_id": "55555555-0000-0000-0000-000000000002",
                "fresh_age_days": 3,
                "stale_age_days": 200,
                "base_score": 0.9,
            },
            expected_output={},
            evaluators=[
                RankHigherThan(
                    higher="55555555-0000-0000-0000-000000000001",
                    lower="55555555-0000-0000-0000-000000000002",
                )
            ],
        ),
        Case(
            name="very_fresh_outranks_moderately_stale",
            inputs={
                "query": "artificial intelligence latest research",
                "fresh_id": "66666666-0000-0000-0000-000000000001",
                "stale_id": "66666666-0000-0000-0000-000000000002",
                "fresh_age_days": 1,
                "stale_age_days": 90,
                "base_score": 0.8,
            },
            expected_output={},
            evaluators=[
                RankHigherThan(
                    higher="66666666-0000-0000-0000-000000000001",
                    lower="66666666-0000-0000-0000-000000000002",
                )
            ],
        ),
        Case(
            name="two_fresh_docs_same_day_preserve_score_order",
            inputs={
                "query": "knowledge graph traversal",
                "first_id": "77777777-0000-0000-0000-000000000001",
                "second_id": "77777777-0000-0000-0000-000000000002",
                "first_age_days": 1,
                "second_age_days": 2,
                "first_base_score": 0.95,
                "second_base_score": 0.70,
            },
            expected_output={},
            evaluators=[
                RankHigherThan(
                    higher="77777777-0000-0000-0000-000000000001",
                    lower="77777777-0000-0000-0000-000000000002",
                )
            ],
        ),
    ],
)
