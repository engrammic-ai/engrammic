"""Similarity-based embedding cache wrapping EmbeddingCache."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from context_service.cache.embedding_cache import EmbeddingCache
from context_service.config.logging import get_logger
from context_service.config.settings import SimilarityCacheConfig

if TYPE_CHECKING:
    from context_service.stores.redis import RedisClient

logger = get_logger(__name__)


class SimilarityEmbeddingCache:
    """Similarity-based embedding cache that wraps EmbeddingCache.

    On exact-match miss, can check a bounded index of recent query vectors
    for cosine similarity > threshold.
    """

    INDEX_KEY_PREFIX = "cache:simidx"

    def __init__(
        self,
        redis: RedisClient,
        exact_cache: EmbeddingCache,
        config: SimilarityCacheConfig,
        provider: str,
    ) -> None:
        self._redis = redis
        self._exact_cache = exact_cache
        self._config = config
        self._provider = provider

    def _index_key(self) -> str:
        """Redis key for similarity index: cache:simidx:{provider}:embeddings"""
        return f"{self.INDEX_KEY_PREFIX}:{self._provider}:embeddings"

    def _encode_entry(self, text_hash: str, vector: list[float]) -> bytes:
        """Encode a (hash, vector) pair as bytes. Hash is 64 bytes + float16 vector bytes."""
        arr = np.array(vector, dtype=np.float16)
        return text_hash.encode() + arr.tobytes()

    def _decode_entry(self, data: bytes) -> tuple[str, np.ndarray]:
        """Decode bytes back to (hash, float16 array)."""
        text_hash = data[:64].decode()
        arr = np.frombuffer(data[64:], dtype=np.float16)
        return text_hash, arr

    def _l2_normalize(self, arr: np.ndarray) -> np.ndarray:
        """L2-normalize an array. Returns original if norm is near zero."""
        norm = float(np.linalg.norm(arr))
        if norm < 1e-10:
            return arr
        return arr / norm

    async def get(self, text: str, task: str) -> list[float] | None:
        """Delegate to exact cache. No similarity lookup without vector."""
        return await self._exact_cache.get(text, task)

    async def set(self, text: str, task: str, vector: list[float]) -> None:
        """Cache in exact cache + push to similarity index if enabled."""
        await self._exact_cache.set(text, task, vector)
        if self._config.enabled:
            text_hash = EmbeddingCache._hash_text(text)
            await self._index_push(text_hash, vector)

    async def similarity_lookup_with_vector(
        self, query_vector: list[float], text_hash: str
    ) -> tuple[str, list[float]] | None:
        """Check index for cosine > threshold. Returns (hash, vector) or None."""
        if not self._config.enabled:
            return None

        try:
            key = self._index_key()
            entries: list[bytes] = await self._redis.lrange(key, 0, -1)
            if not entries:
                return None

            hashes: list[str] = []
            vectors: list[np.ndarray] = []

            for entry in entries:
                h, arr = self._decode_entry(entry)
                # Skip the entry that matches the query's own hash
                if h == text_hash:
                    continue
                hashes.append(h)
                vectors.append(self._l2_normalize(arr.astype(np.float32)))

            if not hashes:
                return None

            query_norm = self._l2_normalize(np.array(query_vector, dtype=np.float32))
            index_matrix = np.stack(vectors)  # shape (N, D)
            similarities = index_matrix @ query_norm  # shape (N,)

            best_idx = int(np.argmax(similarities))
            if similarities[best_idx] >= self._config.threshold:
                return (hashes[best_idx], vectors[best_idx].tolist())

            return None
        except Exception as e:
            logger.debug("similarity_lookup_error", error=str(e))
            return None

    async def _index_push(self, text_hash: str, vector: list[float]) -> None:
        """lpush + ltrim + expire pipeline to maintain bounded index."""
        try:
            key = self._index_key()
            entry = self._encode_entry(text_hash, vector)
            await self._redis.list_push_trim_expire(
                key, entry, self._config.max_entries, self._config.index_ttl
            )
        except Exception as e:
            logger.debug("similarity_index_push_error", error=str(e))
