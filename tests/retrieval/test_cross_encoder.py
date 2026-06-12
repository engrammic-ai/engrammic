"""Tests for the CrossEncoderReranker module."""

from __future__ import annotations

import pytest

from context_service.retrieval.cross_encoder import CrossEncoderReranker, CrossEncoderResult


@pytest.fixture(scope="module")
def reranker() -> CrossEncoderReranker:
    """Module-scoped reranker so the model loads only once across all tests."""
    return CrossEncoderReranker()


def test_rerank_returns_scores(reranker: CrossEncoderReranker) -> None:
    query = "machine learning optimization"
    documents = [
        "Gradient descent is used to minimize loss functions in neural networks.",
        "The weather forecast calls for rain this weekend.",
        "Backpropagation computes gradients for training deep learning models.",
    ]
    node_ids = ["node-1", "node-2", "node-3"]

    results = reranker.rerank(query, documents, node_ids)

    assert len(results) == 3
    for result in results:
        assert isinstance(result, CrossEncoderResult)
        assert isinstance(result.score, float)
        assert result.node_id in node_ids
        assert result.original_index in (0, 1, 2)

    # Results should be sorted descending by score
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_rerank_empty_documents(reranker: CrossEncoderReranker) -> None:
    results = reranker.rerank("any query", [], [])
    assert results == []


def test_rerank_respects_top_k(reranker: CrossEncoderReranker) -> None:
    query = "python programming"
    documents = [
        "Python is a high-level programming language.",
        "Java is used for enterprise applications.",
        "JavaScript runs in the browser.",
        "Rust provides memory safety without a garbage collector.",
        "Go is designed for concurrent server workloads.",
    ]
    node_ids = [f"node-{i}" for i in range(len(documents))]

    results = reranker.rerank(query, documents, node_ids, top_k=3)

    assert len(results) == 3
    # Still sorted descending
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_ml_related_scores_higher_than_weather(reranker: CrossEncoderReranker) -> None:
    """ML-related documents should score higher than unrelated ones for an ML query."""
    query = "neural network training techniques"
    documents = [
        "Dropout regularization prevents overfitting in deep neural networks.",  # relevant
        "Sunny skies expected through the holiday weekend.",  # irrelevant
    ]
    node_ids = ["ml-doc", "weather-doc"]

    results = reranker.rerank(query, documents, node_ids)

    assert len(results) == 2
    top_result = results[0]
    assert top_result.node_id == "ml-doc", (
        f"Expected ML document to rank first, got {top_result.node_id} "
        f"with score {top_result.score:.4f}"
    )


def test_rerank_mismatched_lengths_raises(reranker: CrossEncoderReranker) -> None:
    with pytest.raises(ValueError, match="equal length"):
        reranker.rerank("query", ["doc1", "doc2"], ["node-1"])


def test_rerank_preserves_original_index(reranker: CrossEncoderReranker) -> None:
    query = "database indexing"
    documents = ["B-tree indexes speed up database queries.", "Unrelated topic."]
    node_ids = ["node-a", "node-b"]

    results = reranker.rerank(query, documents, node_ids)

    # original_index should match position in the input list
    for result in results:
        assert result.original_index == node_ids.index(result.node_id)
