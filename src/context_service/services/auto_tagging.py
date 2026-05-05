"""Auto-tagging service with sync cosine matching."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

import numpy as np

if TYPE_CHECKING:
    from context_service.embeddings.base import EmbeddingService
    from context_service.services.tag_config import TagConfigService


@dataclass(slots=True)
class VocabCache:
    """Cached vocabulary with pre-normalized embedding matrix."""

    tags: list[str]
    matrix: np.ndarray  # (n_tags, dim), pre-normalized
    loaded_at: float

    def match(
        self,
        content_vec: np.ndarray,
        threshold: float,
        max_tags: int,
    ) -> list[str]:
        """Find tags with cosine similarity above threshold."""
        if len(self.tags) == 0:
            return []

        # Normalize query vector
        norm = np.linalg.norm(content_vec)
        if norm == 0:
            return []
        vec = content_vec / norm

        # Compute cosine similarities via matrix multiply
        scores = self.matrix @ vec

        # Sort by score descending
        indices = np.argsort(-scores)

        # Filter by threshold and limit
        return [self.tags[i] for i in indices if scores[i] > threshold][:max_tags]


class AutoTaggingService:
    """Service for automatic tag suggestion using cosine similarity."""

    CACHE_TTL = 300  # 5 minutes

    def __init__(
        self,
        embedding: EmbeddingService,
        tag_config: TagConfigService,
    ):
        self._embedding = embedding
        self._tag_config = tag_config
        self._cache: dict[str, VocabCache] = {}

    async def load_vocabulary(self, silo_id: str) -> VocabCache | None:
        """Load and cache vocabulary embeddings for a silo."""
        cached = self._cache.get(silo_id)
        if cached and (time.monotonic() - cached.loaded_at) < self.CACHE_TTL:
            return cached

        tags = await self._tag_config.get_all_tags(UUID(silo_id))
        if not tags:
            return None

        vectors = await self._embedding.embed(tags)
        matrix = np.array(vectors, dtype=np.float32)

        # Pre-normalize rows
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1  # Avoid division by zero
        matrix = matrix / norms

        self._cache[silo_id] = VocabCache(
            tags=tags,
            matrix=matrix,
            loaded_at=time.monotonic(),
        )
        return self._cache[silo_id]

    async def suggest_tags(
        self,
        content_vector: list[float],
        silo_id: str,
        threshold: float = 0.4,
        max_tags: int = 5,
    ) -> list[str]:
        """Suggest tags for content using cosine similarity."""
        vocab = await self.load_vocabulary(silo_id)
        if vocab is None:
            return []

        vec = np.array(content_vector, dtype=np.float32)
        return vocab.match(vec, threshold, max_tags)

    def invalidate(self, silo_id: str) -> None:
        """Invalidate cached vocabulary for a silo."""
        self._cache.pop(silo_id, None)
