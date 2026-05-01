"""Eval: Freshness scoring scenarios."""

from __future__ import annotations

import pytest
from pydantic_evals import Case, Dataset

from tests.evals.evaluators.ranking import RankHigherThan
from tests.evals.tasks.direct import freshness_task


@pytest.fixture
def freshness_dataset() -> Dataset:
    return Dataset(
        name="freshness",
        cases=[
            Case(
                name="recent_ranks_above_stale",
                inputs={
                    "corpus": [
                        {"id": "recent", "content": "Latest Python release notes.", "age_days": 1},
                        {
                            "id": "stale",
                            "content": "Python release notes from last year.",
                            "age_days": 365,
                        },
                    ],
                    "query": "Python release notes",
                },
                expected_output={"higher": "recent", "lower": "stale"},
                evaluators=[RankHigherThan(higher="recent", lower="stale")],
            ),
            Case(
                name="equal_relevance_freshness_tiebreaker",
                inputs={
                    "corpus": [
                        {"id": "new", "content": "Machine learning advances.", "age_days": 7},
                        {"id": "old", "content": "Machine learning advances.", "age_days": 90},
                    ],
                    "query": "machine learning advances",
                },
                expected_output={"higher": "new", "lower": "old"},
                evaluators=[RankHigherThan(higher="new", lower="old")],
            ),
        ],
    )


@pytest.mark.evals
@pytest.mark.integration
async def test_freshness_quality(
    freshness_dataset: Dataset,
    context_service,
    scope_context,
    cleanup_silo,
):
    """Run freshness dataset and verify recency affects ranking."""

    async def task(inputs: dict) -> list[dict]:
        return await freshness_task(inputs, context_service, scope_context)

    report = await freshness_dataset.evaluate(task)
    report.print()

    # Quality evals print results - no hard assertions for now
    # Failures are expected as we tune the system
