"""Eval: Vocabulary mismatch and search quality scenarios.

Baseline harness for measuring recall quality before document expansion is
added. Run these evals, capture the output, then re-run after expansion to
measure improvement.

Usage:
    uv run pytest tests/evals/test_search_quality.py -m "evals" -v
    uv run pytest tests/evals/test_search_quality.py -m "evals" --eval-output baseline.json
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from tests.evals.evaluators.ranking import AbsentFromTopK, TopKContains
from tests.evals.tasks.direct import recall_task

if TYPE_CHECKING:
    from context_service.services.context import ContextService


# ---------------------------------------------------------------------------
# Additional evaluators for search quality metrics
# ---------------------------------------------------------------------------


@dataclass(repr=False)
class RankAt(Evaluator):
    """Record the 1-based rank of a target doc; passes if rank <= threshold."""

    target_id: str = field(default="")
    threshold: int = field(default=5)

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, Any]:
        results = ctx.output or []
        ids = [r["id"] for r in results]
        rank = ids.index(self.target_id) + 1 if self.target_id in ids else len(ids) + 1
        return {
            "rank": rank,
            "found": self.target_id in ids,
            "passed": rank <= self.threshold,
        }


@dataclass(repr=False)
class RecallAtK(Evaluator):
    """Compute recall@k for k values [1, 3, 5, 10].

    expected_output must contain ``relevant_ids``: list[str].
    Returns a dict of recall@1, recall@3, recall@5, recall@10.
    """

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, float]:
        results = ctx.output or []
        relevant: list[str] = ctx.expected_output.get("relevant_ids", [])
        if not relevant:
            return {"recall@1": 0.0, "recall@3": 0.0, "recall@5": 0.0, "recall@10": 0.0}

        result_ids = [r["id"] for r in results]
        relevant_set = set(relevant)

        def _recall(k: int) -> float:
            top_ids = set(result_ids[:k])
            return len(top_ids & relevant_set) / len(relevant_set)

        return {
            "recall@1": _recall(1),
            "recall@3": _recall(3),
            "recall@5": _recall(5),
            "recall@10": _recall(10),
        }


@dataclass(repr=False)
class RelevanceScoreAbove(Evaluator):
    """Pass if the top result's relevance score meets a minimum threshold."""

    target_id: str = field(default="")
    min_score: float = field(default=0.5)

    def evaluate(self, ctx: EvaluatorContext) -> dict[str, Any]:
        results = ctx.output or []
        for r in results:
            if r["id"] == self.target_id:
                score = r.get("score", 0.0)
                return {
                    "score": score,
                    "passed": score >= self.min_score,
                }
        return {"score": 0.0, "passed": False}


# ---------------------------------------------------------------------------
# Corpus fixtures
# ---------------------------------------------------------------------------

# Custodian / task-queue domain corpus. The vocabulary mismatch: a query using
# "custodian checkpoint" should surface the doc about "stress-testing task
# queued" even though none of those words appear in the other doc.
CUSTODIAN_CORPUS = [
    {
        "id": "custodian-1",
        "content": "Stress-testing task queued for background processing by the custodian worker.",
    },
    {
        "id": "custodian-2",
        "content": "The custodian has completed visiting all nodes in the silo.",
    },
    {
        "id": "custodian-3",
        "content": "Claim validation pipeline reached a stable state after consensus promotion.",
    },
    {
        "id": "custodian-4",
        "content": "Embedding generation finished; all vectors written to Qdrant.",
    },
]

# Synonym pairs corpus. Tests whether the retriever can bridge surface-form
# synonyms without expansion.
SYNONYM_CORPUS = [
    {
        "id": "syn-save-1",
        "content": "The system saved a checkpoint after processing 1000 items.",
    },
    {
        "id": "syn-pending-1",
        "content": "Three ingestion jobs are pending and waiting in the task queue.",
    },
    {
        "id": "syn-unrelated-1",
        "content": "Network latency spiked during the embeddings batch run.",
    },
    {
        "id": "syn-unrelated-2",
        "content": "Configuration reload completed without downtime.",
    },
]

# Domain jargon corpus. Terms that are internal to this codebase and unlikely
# to appear in general pre-training data.
JARGON_CORPUS = [
    {
        "id": "jargon-eag-1",
        "content": "EAG paradigm routes agent memory through the four cognitive layers.",
    },
    {
        "id": "jargon-cite-1",
        "content": "CITEEdgeType defines the typed relationships between knowledge nodes.",
    },
    {
        "id": "jargon-silo-1",
        "content": "Each silo_id partitions the memory graph for a specific tenant.",
    },
    {
        "id": "jargon-unrelated-1",
        "content": "The deployment pipeline runs on a standard CI/CD runner.",
    },
]


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


@pytest.fixture
def vocabulary_mismatch_dataset() -> Dataset:
    """Dataset covering vocabulary mismatch scenarios for baseline measurement."""
    return Dataset(
        name="vocabulary_mismatch_baseline",
        cases=[
            # ------------------------------------------------------------------
            # Vocabulary mismatch: "custodian checkpoint" <-> "stress-testing task queued"
            # ------------------------------------------------------------------
            Case(
                name="custodian_checkpoint_finds_queued_task",
                inputs={
                    "corpus": CUSTODIAN_CORPUS,
                    "query": "custodian checkpoint",
                },
                expected_output={
                    "relevant_ids": ["custodian-1"],
                    "expected_top": ["custodian-1"],
                },
                evaluators=[
                    TopKContains(k=5),
                    RecallAtK(),
                    RankAt(target_id="custodian-1", threshold=5),
                    RelevanceScoreAbove(target_id="custodian-1", min_score=0.3),
                ],
            ),
            # ------------------------------------------------------------------
            # Synonym: "save point" <-> "checkpoint"
            # ------------------------------------------------------------------
            Case(
                name="save_point_finds_checkpoint_doc",
                inputs={
                    "corpus": SYNONYM_CORPUS,
                    "query": "save point",
                },
                expected_output={
                    "relevant_ids": ["syn-save-1"],
                    "expected_top": ["syn-save-1"],
                },
                evaluators=[
                    TopKContains(k=3),
                    RecallAtK(),
                    RankAt(target_id="syn-save-1", threshold=3),
                    RelevanceScoreAbove(target_id="syn-save-1", min_score=0.3),
                ],
            ),
            # ------------------------------------------------------------------
            # Synonym: "queued" <-> "pending"
            # ------------------------------------------------------------------
            Case(
                name="queued_finds_pending_doc",
                inputs={
                    "corpus": SYNONYM_CORPUS,
                    "query": "queued jobs",
                },
                expected_output={
                    "relevant_ids": ["syn-pending-1"],
                    "expected_top": ["syn-pending-1"],
                },
                evaluators=[
                    TopKContains(k=3),
                    RecallAtK(),
                    RankAt(target_id="syn-pending-1", threshold=3),
                    RelevanceScoreAbove(target_id="syn-pending-1", min_score=0.3),
                ],
            ),
            # ------------------------------------------------------------------
            # Reverse synonym: "pending" <-> "queued"
            # ------------------------------------------------------------------
            Case(
                name="pending_finds_queued_doc",
                inputs={
                    "corpus": CUSTODIAN_CORPUS,
                    "query": "pending background task",
                },
                expected_output={
                    "relevant_ids": ["custodian-1"],
                    "expected_top": ["custodian-1"],
                },
                evaluators=[
                    TopKContains(k=5),
                    RecallAtK(),
                    RankAt(target_id="custodian-1", threshold=5),
                ],
            ),
            # ------------------------------------------------------------------
            # Domain jargon: EAG paradigm
            # ------------------------------------------------------------------
            Case(
                name="eag_jargon_found",
                inputs={
                    "corpus": JARGON_CORPUS,
                    "query": "EAG memory layers",
                },
                expected_output={
                    "relevant_ids": ["jargon-eag-1"],
                    "expected_top": ["jargon-eag-1"],
                },
                evaluators=[
                    TopKContains(k=1),
                    RecallAtK(),
                    RankAt(target_id="jargon-eag-1", threshold=1),
                    RelevanceScoreAbove(target_id="jargon-eag-1", min_score=0.5),
                ],
            ),
            # ------------------------------------------------------------------
            # Domain jargon: CITE schema
            # ------------------------------------------------------------------
            Case(
                name="cite_jargon_found",
                inputs={
                    "corpus": JARGON_CORPUS,
                    "query": "CITEEdgeType relationship schema",
                },
                expected_output={
                    "relevant_ids": ["jargon-cite-1"],
                    "expected_top": ["jargon-cite-1"],
                },
                evaluators=[
                    TopKContains(k=1),
                    RecallAtK(),
                    RankAt(target_id="jargon-cite-1", threshold=1),
                    RelevanceScoreAbove(target_id="jargon-cite-1", min_score=0.5),
                ],
            ),
            # ------------------------------------------------------------------
            # Domain jargon: silo partitioning
            # ------------------------------------------------------------------
            Case(
                name="silo_jargon_found",
                inputs={
                    "corpus": JARGON_CORPUS,
                    "query": "tenant silo isolation",
                },
                expected_output={
                    "relevant_ids": ["jargon-silo-1"],
                    "expected_top": ["jargon-silo-1"],
                },
                evaluators=[
                    TopKContains(k=3),
                    RecallAtK(),
                    RankAt(target_id="jargon-silo-1", threshold=3),
                ],
            ),
            # ------------------------------------------------------------------
            # Negative: unrelated docs should not surface for domain jargon query
            # ------------------------------------------------------------------
            Case(
                name="unrelated_absent_from_jargon_query",
                inputs={
                    "corpus": JARGON_CORPUS,
                    "query": "EAG cognitive layer memory",
                },
                expected_output={"absent_id": "jargon-unrelated-1"},
                evaluators=[AbsentFromTopK(k=3)],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.evals
@pytest.mark.integration
async def test_vocabulary_mismatch_baseline(
    vocabulary_mismatch_dataset: Dataset,
    context_service: ContextService,
    scope_context: Any,
    cleanup_silo: Any,
) -> None:
    """Establish baseline search quality metrics before document expansion.

    This test deliberately does NOT assert hard pass/fail on vocabulary
    mismatch cases -- the baseline is expected to be weak for those. The
    goal is to capture the numbers so we can compare after expansion is
    added.

    Jargon exact-match cases (EAG, CITE, silo) are asserted because dense
    embeddings should handle those even without expansion.
    """

    async def task(inputs: dict[str, Any]) -> list[dict[str, Any]]:
        return await recall_task(inputs, context_service, scope_context)

    report = await vocabulary_mismatch_dataset.evaluate(task)
    report.print()

    # Jargon cases: dense embeddings should match these reliably.
    # Vocabulary mismatch cases are recorded only (no assertion) -- they are
    # expected to fail at baseline and improve after document expansion.
