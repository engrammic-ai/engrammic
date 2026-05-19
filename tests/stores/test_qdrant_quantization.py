"""Unit tests for Qdrant quantization config settings — no live Qdrant required."""

from __future__ import annotations

from context_service.config.settings import QdrantConfig, Settings


def test_quantization_settings_defaults() -> None:
    config = QdrantConfig()
    assert config.scalar_quantization_enabled is False
    assert config.quantization_always_ram is True


def test_quantization_settings_enabled() -> None:
    config = QdrantConfig(scalar_quantization_enabled=True, quantization_always_ram=False)
    assert config.scalar_quantization_enabled is True
    assert config.quantization_always_ram is False


def test_settings_flat_shims_defaults() -> None:
    settings = Settings()
    assert settings.qdrant_scalar_quantization_enabled is False
    assert settings.qdrant_quantization_always_ram is True
