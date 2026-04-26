"""Embedding service protocol for provider-agnostic embedding generation."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingService(Protocol):
    """Protocol that all embedding providers must implement."""

    @property
    def dimensions(self) -> int:
        """Output embedding dimensions."""
        ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        ...

    async def embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        ...

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a search query."""
        ...

    async def close(self) -> None:
        """Close any resources."""
        ...
