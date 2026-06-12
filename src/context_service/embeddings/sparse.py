"""Sparse encoder protocol for hybrid search."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SparseEncoder(Protocol):
    """Protocol for sparse text encoders (BM25, SPLADE, etc.)."""

    async def encode(self, text: str) -> dict[int, float]:
        """Encode a single text to a sparse vector."""
        ...

    async def encode_query(self, query: str) -> dict[int, float]:
        """Encode a search query to a sparse vector."""
        ...

    async def encode_batch(self, texts: list[str]) -> list[dict[int, float]]:
        """Encode a batch of texts to sparse vectors."""
        ...

    @staticmethod
    def to_qdrant(sparse: dict[int, float]) -> tuple[list[int], list[float]]:
        """Convert sparse dict to Qdrant's (indices, values) format."""
        ...


def get_sparse_encoder(provider: str = "fastembed", model: str | None = None) -> SparseEncoder:
    """Factory to get sparse encoder by provider.

    Args:
        provider: "fastembed" (BM25, ONNX) or "splade" (torch)
        model: Model name override

    Returns:
        SparseEncoder instance
    """
    if provider == "fastembed":
        from context_service.embeddings.bm25 import BM25Encoder

        return BM25Encoder(model_name=model or "Qdrant/bm25")
    elif provider == "splade":
        from context_service.embeddings.splade import SpladeEncoder

        return SpladeEncoder(model_name=model or "prithivida/Splade_PP_en_v1")
    else:
        raise ValueError(f"Unknown sparse encoder provider: {provider}")
