"""SPLADE sparse encoder for hybrid dense+sparse retrieval."""

from __future__ import annotations

import asyncio
from typing import Any

from context_service.config.logging import get_logger
from context_service.telemetry.tracing import traced

logger = get_logger(__name__)

_DEFAULT_MODEL = "prithivida/Splade_PP_en_v1"


class SpladeEncoderError(Exception):
    """Raised when SPLADE encoding operations fail."""


class SpladeEncoder:
    """Async SPLADE sparse encoder using a local HuggingFace model.

    Implements the sparse-vector analogue of the ``EmbeddingService`` protocol:
    instead of ``list[float]`` dense vectors, the output is ``dict[int, float]``
    mapping vocabulary token indices to their activation weights.

    Model loading is lazy — the tokenizer and model are not imported or loaded
    at construction time. They are loaded on the first call to ``encode`` or
    ``encode_batch``. This keeps import time fast and avoids loading a ~500 MB
    model for processes that never do sparse encoding (e.g., tests that mock the
    encoder).
    """

    def __init__(self, model_name: str = _DEFAULT_MODEL) -> None:
        """Initialise the encoder.

        Args:
            model_name: HuggingFace model identifier. Defaults to
                ``prithivida/Splade_PP_en_v1`` — a lighter SPLADE++ variant
                that is viable on CPU.
        """
        self._model_name = model_name
        self._tokenizer: Any = None
        self._model: Any = None
        self._load_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_lock(self) -> asyncio.Lock:
        """Return the per-instance load lock, creating it lazily.

        The lock must be created inside the running event loop, so we
        create it on first access rather than in ``__init__``.
        """
        if self._load_lock is None:
            self._load_lock = asyncio.Lock()
        return self._load_lock

    async def _ensure_loaded(self) -> None:
        """Load the tokenizer and model if not already loaded (thread-safe)."""
        if self._model is not None:
            return

        async with self._get_lock():
            # Double-checked: another coroutine may have loaded while we waited.
            if self._model is not None:
                return

            logger.info("splade_loading", model=self._model_name)
            try:
                from transformers import (  # type: ignore[import-not-found]
                    AutoModelForMaskedLM,
                    AutoTokenizer,
                )
            except ImportError as exc:
                raise SpladeEncoderError(
                    "SPLADE requires 'torch' and 'transformers'. "
                    "Install the 'splade' extra: uv sync --extra splade"
                ) from exc

            loop = asyncio.get_running_loop()
            tokenizer, model = await loop.run_in_executor(
                None,
                lambda: (
                    AutoTokenizer.from_pretrained(self._model_name),
                    AutoModelForMaskedLM.from_pretrained(self._model_name),
                ),
            )
            model.eval()
            self._tokenizer = tokenizer
            self._model = model
            logger.info("splade_loaded", model=self._model_name)

    def _encode_batch_sync(self, texts: list[str]) -> list[dict[int, float]]:
        """CPU-bound encoding — called via run_in_executor."""
        import torch  # type: ignore[import-not-found]

        inputs = self._tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512,
        )

        with torch.no_grad():
            logits = self._model(**inputs).logits  # (batch, seq_len, vocab)

        # SPLADE activation: max-pool over token positions, then ReLU + log(1+x)
        # Produces a (batch, vocab) sparse representation.
        activations = torch.log1p(torch.relu(logits)).max(dim=1).values  # (batch, vocab)

        results: list[dict[int, float]] = []
        for row in activations:
            indices = row.nonzero(as_tuple=False).squeeze(dim=1)
            values = row[indices]
            results.append(
                {
                    int(idx): float(val)
                    for idx, val in zip(indices.tolist(), values.tolist(), strict=False)
                }
            )
        return results

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    @traced(capture_args=["texts"])
    async def encode_batch(self, texts: list[str]) -> list[dict[int, float]]:
        """Encode a batch of texts to sparse vectors.

        Args:
            texts: Texts to encode. Empty list returns an empty list.

        Returns:
            One ``dict[int, float]`` per text, mapping vocabulary token index
            to activation weight. Zero-activation tokens are omitted.

        Raises:
            SpladeEncoderError: If the model cannot be loaded or encoding fails.
        """
        if not texts:
            return []

        await self._ensure_loaded()

        loop = asyncio.get_running_loop()
        try:
            results = await loop.run_in_executor(None, self._encode_batch_sync, texts)
        except Exception as exc:
            logger.error("splade_encode_error", error=str(exc))
            raise SpladeEncoderError(f"Sparse encoding failed: {exc}") from exc

        logger.debug("splade_encode_batch", count=len(texts))
        return results

    async def encode(self, text: str) -> dict[int, float]:
        """Encode a single text to a sparse vector.

        Args:
            text: Text to encode.

        Returns:
            Sparse vector as ``dict[int, float]``.

        Raises:
            SpladeEncoderError: If encoding fails.
        """
        results = await self.encode_batch([text])
        return results[0]

    async def encode_query(self, query: str) -> dict[int, float]:
        """Encode a search query to a sparse vector.

        For SPLADE++ the passage and query paths use the same model
        (unlike asymmetric models). This method is a semantic alias for
        ``encode``, preserving API symmetry with ``EmbeddingService``.

        Args:
            query: Search query text.

        Returns:
            Sparse vector as ``dict[int, float]``.
        """
        return await self.encode(query)

    @staticmethod
    def to_qdrant(sparse: dict[int, float]) -> tuple[list[int], list[float]]:
        """Convert a sparse vector dict to Qdrant's (indices, values) format.

        Args:
            sparse: Sparse vector mapping token index -> weight.

        Returns:
            Tuple of (indices, values) lists suitable for
            ``qdrant_client.models.SparseVector``.
        """
        if not sparse:
            return [], []
        indices, values = zip(*sorted(sparse.items()), strict=True)
        return list(indices), list(values)
