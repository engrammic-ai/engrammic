"""Tests for build_embedding_service factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from context_service.embeddings import (
    LiteLLMEmbeddingService,
    TEIWithFallbackEmbeddingService,
)


@pytest.fixture
def mock_litellm_settings() -> MagicMock:
    """Mock settings with litellm provider."""
    mock_embed_spec = MagicMock()
    mock_embed_spec.provider = "litellm"

    mock_models = MagicMock()
    mock_models.get_embedding_model.return_value = mock_embed_spec

    mock_settings = MagicMock()
    mock_settings.models = mock_models
    return mock_settings


@pytest.fixture
def mock_tei_settings() -> MagicMock:
    """Mock settings with tei provider."""
    mock_embed_spec = MagicMock()
    mock_embed_spec.provider = "tei"

    mock_models = MagicMock()
    mock_models.get_embedding_model.return_value = mock_embed_spec
    mock_models.embedding_dimensions = 768

    mock_settings = MagicMock()
    mock_settings.models = mock_models
    mock_settings.tei_url = "http://localhost:8080"
    return mock_settings


def test_build_litellm_when_provider_litellm(mock_litellm_settings: MagicMock) -> None:
    """Factory should return LiteLLMEmbeddingService when provider=litellm."""
    with patch(
        "context_service.embeddings.get_settings", return_value=mock_litellm_settings
    ):
        from context_service.embeddings import build_embedding_service

        service = build_embedding_service()
        assert isinstance(service, LiteLLMEmbeddingService)


def test_build_tei_when_provider_tei(mock_tei_settings: MagicMock) -> None:
    """Factory should return TEIWithFallbackEmbeddingService when provider=tei."""
    with patch("context_service.embeddings.get_settings", return_value=mock_tei_settings):
        from context_service.embeddings import build_embedding_service

        service = build_embedding_service()
        assert isinstance(service, TEIWithFallbackEmbeddingService)
