"""BM25 sparse encoder using FastEmbed for hybrid dense+sparse retrieval."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from context_service.config.logging import get_logger
from context_service.telemetry.tracing import traced

if TYPE_CHECKING:
    from fastembed import SparseTextEmbedding

logger = get_logger(__name__)

_DEFAULT_MODEL = "Qdrant/bm25"


class BM25EncoderError(Exception):
    """Raised when BM25 encoding operations fail."""


class BM25Encoder:
    """Async BM25 sparse encoder using FastEmbed.

    Implements the same protocol as SpladeEncoder but uses FastEmbed's BM25
    model which runs on ONNX runtime (no torch/CUDA required). Much faster
    builds and smaller image size (~100MB vs 2GB+).

    Model loading is lazy - the encoder is not loaded until first use.
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        self._model_name = model_name
        self._encoder: SparseTextEmbedding | None = None
        self._load_lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    async def _ensure_loaded(self) -> None:
        if self._encoder is not None:
            return

        async with self._get_lock():
            if self._encoder is not None:
                return

            logger.info("bm25_loading", model=self._model_name)
            try:
                from fastembed import SparseTextEmbedding
            except ImportError as exc:
                raise BM25EncoderError(
                    "BM25 requires fastembed. Install with: uv sync --group sparse"
                ) from exc

            loop = asyncio.get_running_loop()
            self._encoder = await loop.run_in_executor(
                None,
                lambda: SparseTextEmbedding(model_name=self._model_name),
            )
            logger.info("bm25_loaded", model=self._model_name)

    def _encode_batch_sync(self, texts: list[str]) -> list[dict[int, float]]:
        """CPU-bound encoding."""
        assert self._encoder is not None
        results: list[dict[int, float]] = []
        for embedding in self._encoder.embed(texts):
            sparse_dict = {
                int(idx): float(val)
                for idx, val in zip(embedding.indices, embedding.values, strict=False)
            }
            results.append(sparse_dict)
        return results

    @traced(capture_args=["texts"])
    async def encode_batch(self, texts: list[str]) -> list[dict[int, float]]:
        """Encode a batch of texts to sparse vectors.

        Returns:
            One dict[int, float] per text, mapping token index to weight.
        """
        if not texts:
            return []

        await self._ensure_loaded()

        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(None, self._encode_batch_sync, texts)
        except Exception as exc:
            logger.error("bm25_encode_error", error=str(exc))
            raise BM25EncoderError(f"Sparse encoding failed: {exc}") from exc

        logger.debug("bm25_encode_batch", count=len(texts))
        return results

    async def encode(self, text: str) -> dict[int, float]:
        """Encode a single text to a sparse vector."""
        results = await self.encode_batch([text])
        return results[0]

    async def encode_query(self, query: str) -> dict[int, float]:
        """Encode a search query to a sparse vector."""
        return await self.encode(query)

    @staticmethod
    def to_qdrant(sparse: dict[int, float]) -> tuple[list[int], list[float]]:
        """Convert sparse dict to Qdrant's (indices, values) format."""
        if not sparse:
            return [], []
        indices, values = zip(*sorted(sparse.items()), strict=True)
        return list(indices), list(values)
