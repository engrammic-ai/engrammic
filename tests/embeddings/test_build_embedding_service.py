"""Tests for build_embedding_service factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from context_service.embeddings import (
    LiteLLMEmbeddingService,
    TEIWithFallbackEmbeddingService,
)


@pytest.fixture
def mock_litellm_config() -> dict:
    return {"provider": "litellm", "model": "test/model", "dimensions": 768}


@pytest.fixture
def mock_tei_config() -> dict:
    return {"provider": "tei", "dimensions": 768}


def test_build_litellm_when_provider_litellm(mock_litellm_config: dict) -> None:
    """Factory should return LiteLLMEmbeddingService when provider=litellm."""
    with patch("context_service.embeddings.load_config", return_value=mock_litellm_config):
        # Import inside patch scope to get the patched version
        from context_service.embeddings import build_embedding_service

        service = build_embedding_service()
        assert isinstance(service, LiteLLMEmbeddingService)


def test_build_tei_when_provider_tei(mock_tei_config: dict) -> None:
    """Factory should return TEIWithFallbackEmbeddingService when provider=tei."""
    mock_settings = MagicMock()
    mock_settings.tei_url = "http://localhost:8080"

    with (
        patch("context_service.embeddings.load_config", return_value=mock_tei_config),
        patch(
            "context_service.embeddings.get_settings",
            return_value=mock_settings,
        ),
    ):
        from context_service.embeddings import build_embedding_service

        service = build_embedding_service()
        assert isinstance(service, TEIWithFallbackEmbeddingService)


def test_build_tei_raises_without_tei_url(mock_tei_config: dict) -> None:
    """Factory should raise RuntimeError when provider=tei but TEI_URL not set."""
    mock_settings = MagicMock()
    mock_settings.tei_url = None

    with (
        patch("context_service.embeddings.load_config", return_value=mock_tei_config),
        patch(
            "context_service.embeddings.get_settings",
            return_value=mock_settings,
        ),
    ):
        from context_service.embeddings import build_embedding_service

        with pytest.raises(RuntimeError, match="TEI_URL is not configured"):
            build_embedding_service()
