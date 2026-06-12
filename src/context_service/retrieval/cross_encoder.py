"""Cross-encoder reranker for TEMPR retrieval.

Uses a sentence-transformers CrossEncoder model to score query-document pairs
and reorder results by relevance. Designed as a late-stage reranker that runs
after initial retrieval channels have already returned candidate node IDs.

The model is lazy-loaded on first use and cached for the lifetime of the process.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache(maxsize=4)
def _load_model(model_name: str) -> Any:
    """Load and cache a CrossEncoder model by name.

    The lru_cache ensures the same model is only loaded once per process,
    regardless of how many CrossEncoderReranker instances are created.
    """
    from sentence_transformers import CrossEncoder

    logger.info("loading_cross_encoder_model", model=model_name)
    return CrossEncoder(model_name)


@dataclass
class CrossEncoderResult:
    """Single document after cross-encoder scoring.

    Attributes:
        node_id: UUID string of the context node.
        score: Raw cross-encoder relevance score (higher is more relevant).
        original_index: Position of this document in the input list, before reranking.
    """

    node_id: str
    score: float
    original_index: int


class CrossEncoderReranker:
    """Reranks retrieved documents using a cross-encoder model.

    Cross-encoders jointly encode the query and document, producing a
    relevance score that is more accurate than bi-encoder cosine similarity
    but more expensive to compute (O(n) model forward passes).

    Args:
        model: HuggingFace model identifier for a sentence-transformers CrossEncoder.
            Defaults to ms-marco-MiniLM-L-6-v2, which balances speed and quality
            for passage reranking tasks.
    """

    def __init__(self, model: str = _DEFAULT_MODEL) -> None:
        self._model_name = model

    @property
    def _model(self) -> Any:
        return _load_model(self._model_name)

    def rerank(
        self,
        query: str,
        documents: list[str],
        node_ids: list[str],
        top_k: int | None = None,
    ) -> list[CrossEncoderResult]:
        """Score and rerank documents by relevance to the query.

        Args:
            query: The search query string.
            documents: Document texts corresponding to each node_id.
            node_ids: Node IDs parallel to the documents list.
            top_k: If provided, return only the top_k highest-scoring results.
                   If None, return all results sorted by score descending.

        Returns:
            List of CrossEncoderResult sorted by score descending.

        Raises:
            ValueError: If documents and node_ids have different lengths.
        """
        if len(documents) != len(node_ids):
            raise ValueError(
                f"documents and node_ids must have equal length, "
                f"got {len(documents)} and {len(node_ids)}"
            )

        if not documents:
            return []

        pairs = [(query, doc) for doc in documents]

        logger.debug(
            "cross_encoder_reranking",
            model=self._model_name,
            n_candidates=len(documents),
            top_k=top_k,
        )

        raw_scores: list[float] = self._model.predict(pairs).tolist()

        results = [
            CrossEncoderResult(
                node_id=node_ids[i],
                score=float(raw_scores[i]),
                original_index=i,
            )
            for i in range(len(documents))
        ]

        results.sort(key=lambda r: r.score, reverse=True)

        if top_k is not None:
            results = results[:top_k]

        return results
