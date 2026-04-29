"""Unit tests for SpladeEncoder — no model download required.

All tests mock the heavy torch / transformers dependencies so the suite
runs without the 'splade' extra installed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from context_service.embeddings.splade import SpladeEncoder, SpladeEncoderError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_encoder(model_name: str = "prithivida/Splade_PP_en_v1") -> SpladeEncoder:
    return SpladeEncoder(model_name=model_name)


# ---------------------------------------------------------------------------
# to_qdrant static helper — pure sync, no async needed
# ---------------------------------------------------------------------------


class TestToQdrant:
    def test_empty_sparse_returns_empty_lists(self) -> None:
        indices, values = SpladeEncoder.to_qdrant({})
        assert indices == []
        assert values == []

    def test_output_sorted_by_index(self) -> None:
        sparse = {5: 0.5, 1: 0.9, 3: 0.2}
        indices, values = SpladeEncoder.to_qdrant(sparse)
        assert indices == [1, 3, 5]
        assert values == [0.9, 0.2, 0.5]

    def test_single_entry(self) -> None:
        indices, values = SpladeEncoder.to_qdrant({42: 0.7})
        assert indices == [42]
        assert values == [0.7]

    def test_output_has_no_zero_values(self) -> None:
        """to_qdrant contract: zero activations should not appear in filtered input."""
        sparse = {1: 0.5, 3: 0.8}
        indices, values = SpladeEncoder.to_qdrant(sparse)
        assert 0.0 not in values


# ---------------------------------------------------------------------------
# encode_batch (mocked model)
# ---------------------------------------------------------------------------


class TestEncodeBatch:
    async def test_empty_input_returns_empty_list(self) -> None:
        encoder = _make_encoder()
        result = await encoder.encode_batch([])
        assert result == []

    async def test_returns_one_dict_per_text(self) -> None:
        encoder = _make_encoder()

        # Pre-built sparse results — no torch dependency.
        expected: list[dict[int, float]] = [
            {10: 0.5, 20: 0.8},
            {5: 0.3, 100: 1.2},
            {7: 0.9},
        ]

        with (
            patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock),
            patch.object(encoder, "_encode_batch_sync", return_value=expected),
        ):
            result = await encoder.encode_batch(["text a", "text b", "text c"])

        assert len(result) == 3
        for sparse in result:
            assert isinstance(sparse, dict)
            assert all(isinstance(k, int) for k in sparse)
            assert all(isinstance(v, float) for v in sparse.values())

    async def test_encode_single_delegates_to_batch(self) -> None:
        encoder = _make_encoder()
        expected: list[dict[int, float]] = [{7: 0.3, 12: 0.9}]

        with (
            patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock),
            patch.object(encoder, "_encode_batch_sync", return_value=expected),
        ):
            result = await encoder.encode("hello")

        assert result == {7: 0.3, 12: 0.9}

    async def test_encode_query_delegates_to_encode(self) -> None:
        encoder = _make_encoder()
        expected: list[dict[int, float]] = [{100: 1.0}]

        with (
            patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock),
            patch.object(encoder, "_encode_batch_sync", return_value=expected),
        ):
            result = await encoder.encode_query("q")

        assert result == {100: 1.0}

    async def test_encode_error_raises_splade_error(self) -> None:
        encoder = _make_encoder()

        with patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock), patch.object(
            encoder, "_encode_batch_sync", side_effect=RuntimeError("boom")
        ), pytest.raises(SpladeEncoderError, match="Sparse encoding failed"):
            await encoder.encode_batch(["x"])

    async def test_sparse_vector_keys_are_ints_values_are_floats(self) -> None:
        encoder = _make_encoder()
        raw: list[dict[int, float]] = [{0: 0.1, 999: 2.5, 500: 0.7}]

        with (
            patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock),
            patch.object(encoder, "_encode_batch_sync", return_value=raw),
        ):
            result = await encoder.encode_batch(["anything"])

        sparse = result[0]
        assert all(isinstance(k, int) for k in sparse)
        assert all(isinstance(v, float) for v in sparse.values())

    async def test_batch_encodes_each_text_independently(self) -> None:
        """Each text in a batch should produce its own sparse dict."""
        encoder = _make_encoder()
        expected: list[dict[int, float]] = [
            {1: 0.5},
            {2: 0.6},
            {3: 0.7},
            {4: 0.8},
            {5: 0.9},
        ]

        with (
            patch.object(encoder, "_ensure_loaded", new_callable=AsyncMock),
            patch.object(encoder, "_encode_batch_sync", return_value=expected),
        ):
            result = await encoder.encode_batch(["a", "b", "c", "d", "e"])

        assert result == expected


# ---------------------------------------------------------------------------
# _ensure_loaded: import-error branch
# ---------------------------------------------------------------------------


class TestEnsureLoaded:
    async def test_missing_torch_raises_encoder_error(self) -> None:
        encoder = _make_encoder()

        with (
            patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")),
            pytest.raises((SpladeEncoderError, ImportError)),
        ):
            await encoder._ensure_loaded()
