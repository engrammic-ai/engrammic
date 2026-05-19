"""Unit tests for SimilarityEmbeddingCache."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

import numpy as np
import pytest

from context_service.cache.embedding_cache import EmbeddingCache
from context_service.cache.similarity_cache import SimilarityEmbeddingCache
from context_service.config.settings import SimilarityCacheConfig

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.lrange = AsyncMock(return_value=[])
    redis.list_push_trim_expire = AsyncMock()
    return redis


@pytest.fixture
def mock_exact_cache() -> AsyncMock:
    cache = AsyncMock(spec=EmbeddingCache)
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    return cache


@pytest.fixture
def enabled_config() -> SimilarityCacheConfig:
    return SimilarityCacheConfig(enabled=True, threshold=0.95, max_entries=100)


@pytest.fixture
def disabled_config() -> SimilarityCacheConfig:
    return SimilarityCacheConfig(enabled=False)


def make_cache(
    mock_redis: AsyncMock,
    mock_exact_cache: AsyncMock,
    config: SimilarityCacheConfig,
    provider: str = "tei",
) -> SimilarityEmbeddingCache:
    return SimilarityEmbeddingCache(mock_redis, mock_exact_cache, config, provider)


# ---------------------------------------------------------------------------
# Codec tests
# ---------------------------------------------------------------------------


def test_encode_decode_roundtrip(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """float16 codec preserves vector within tolerance."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    text_hash = "a" * 64
    vector = [0.1, 0.2, 0.3, 0.4, 0.5]

    data = cache._encode_entry(text_hash, vector)
    decoded_hash, decoded_arr = cache._decode_entry(data)

    assert decoded_hash == text_hash
    np.testing.assert_allclose(decoded_arr, np.array(vector, dtype=np.float16), rtol=1e-3)


def test_set_converts_float32_to_float16(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Input list[float] stored as float16 in index entry."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    text_hash = "b" * 64
    vector = [0.123456789, -0.987654321, 0.5]

    data = cache._encode_entry(text_hash, vector)
    _, decoded_arr = cache._decode_entry(data)

    # Dtype must be float16
    assert decoded_arr.dtype == np.float16
    # Values differ from full-precision float32 but stay within float16 tolerance
    expected = np.array(vector, dtype=np.float16)
    np.testing.assert_allclose(decoded_arr, expected, rtol=1e-3)


# ---------------------------------------------------------------------------
# L2 normalization tests
# ---------------------------------------------------------------------------


def test_l2_normalize_unit_vector(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Unit vector is unchanged after normalization."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    arr = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    result = cache._l2_normalize(arr)
    np.testing.assert_allclose(result, arr, atol=1e-6)


def test_l2_normalize_zero_vector(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Zero vector is returned as-is without raising."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    arr = np.zeros(4, dtype=np.float32)
    result = cache._l2_normalize(arr)
    np.testing.assert_array_equal(result, arr)


# ---------------------------------------------------------------------------
# set() behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_pushes_to_index(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """set() populates index when enabled."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    vector = [0.1] * 512

    await cache.set("test query", "search_query", vector)

    mock_exact_cache.set.assert_called_once_with("test query", "search_query", vector)
    mock_redis.list_push_trim_expire.assert_called_once()


@pytest.mark.asyncio
async def test_disabled_skips_index(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, disabled_config: SimilarityCacheConfig) -> None:
    """set() does not touch index when enabled=False."""
    cache = make_cache(mock_redis, mock_exact_cache, disabled_config)
    vector = [0.1] * 512

    await cache.set("test query", "search_query", vector)

    mock_exact_cache.set.assert_called_once()
    mock_redis.list_push_trim_expire.assert_not_called()


@pytest.mark.asyncio
async def test_index_trims_to_max_entries(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """list_push_trim_expire is called with correct max_entries."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    vector = [0.5] * 128

    await cache.set("some text", "search_query", vector)

    call_args = mock_redis.list_push_trim_expire.call_args
    # Signature: list_push_trim_expire(key, entry, max_entries, ttl)
    _, kwargs = call_args if call_args.kwargs else (call_args.args, {})
    positional = call_args.args
    assert positional[2] == enabled_config.max_entries


# ---------------------------------------------------------------------------
# similarity_lookup_with_vector tests
# ---------------------------------------------------------------------------


def _make_entry(cache: SimilarityEmbeddingCache, text_hash: str, vector: list[float]) -> bytes:
    return cache._encode_entry(text_hash, vector)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.mark.asyncio
async def test_similarity_lookup_above_threshold(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Near-identical vector returns a match."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)

    base = np.ones(64, dtype=np.float32)
    base /= np.linalg.norm(base)

    stored_hash = _sha256("stored text")
    stored_vector = base.tolist()
    entry = _make_entry(cache, stored_hash, stored_vector)
    mock_redis.lrange.return_value = [entry]

    # Query with a slightly perturbed vector (still very close)
    query_vector = (base + np.random.default_rng(42).normal(0, 0.001, 64)).tolist()
    query_hash = _sha256("query text")

    result = await cache.similarity_lookup_with_vector(query_vector, query_hash)

    assert result is not None
    matched_hash, _ = result
    assert matched_hash == stored_hash


@pytest.mark.asyncio
async def test_similarity_lookup_below_threshold(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Orthogonal vector returns None."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)

    stored_hash = _sha256("stored text")
    # First unit basis vector
    stored_vector = [1.0] + [0.0] * 63
    entry = _make_entry(cache, stored_hash, stored_vector)
    mock_redis.lrange.return_value = [entry]

    # Orthogonal query vector
    query_vector = [0.0, 1.0] + [0.0] * 62
    query_hash = _sha256("query text")

    result = await cache.similarity_lookup_with_vector(query_vector, query_hash)

    assert result is None


@pytest.mark.asyncio
async def test_similarity_lookup_empty_index(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Returns None gracefully when index is empty."""
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)
    mock_redis.lrange.return_value = []

    result = await cache.similarity_lookup_with_vector([0.1] * 32, _sha256("q"))

    assert result is None


@pytest.mark.asyncio
async def test_similarity_lookup_disabled(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, disabled_config: SimilarityCacheConfig) -> None:
    """Returns None without touching Redis when disabled."""
    cache = make_cache(mock_redis, mock_exact_cache, disabled_config)

    result = await cache.similarity_lookup_with_vector([0.1] * 32, _sha256("q"))

    assert result is None
    mock_redis.lrange.assert_not_called()


# ---------------------------------------------------------------------------
# get() delegation tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_exact_match_wins(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """get() returns exact cached embedding when present."""
    cached_vector = [0.1, 0.2, 0.3]
    mock_exact_cache.get.return_value = cached_vector
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)

    result = await cache.get("some text", "search_query")

    assert result == cached_vector
    mock_exact_cache.get.assert_called_once_with("some text", "search_query")


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """get() returns None when nothing cached."""
    mock_exact_cache.get.return_value = None
    cache = make_cache(mock_redis, mock_exact_cache, enabled_config)

    result = await cache.get("unknown text", "search_query")

    assert result is None


# ---------------------------------------------------------------------------
# Provider namespace isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_different_providers_use_different_indexes(mock_redis: AsyncMock, mock_exact_cache: AsyncMock, enabled_config: SimilarityCacheConfig) -> None:
    """Provider namespace prevents cross-contamination between providers."""
    cache_a = make_cache(mock_redis, mock_exact_cache, enabled_config, provider="tei")
    cache_b = make_cache(mock_redis, mock_exact_cache, enabled_config, provider="openai")

    key_a = cache_a._index_key()
    key_b = cache_b._index_key()

    assert key_a != key_b
    assert "tei" in key_a
    assert "openai" in key_b

    # Writing to provider A should use a different Redis key than provider B
    vector = [0.1] * 32
    await cache_a.set("text", "task", vector)
    await cache_b.set("text", "task", vector)

    calls = mock_redis.list_push_trim_expire.call_args_list
    assert len(calls) == 2
    key_used_a = calls[0].args[0]
    key_used_b = calls[1].args[0]
    assert key_used_a != key_used_b
