"""Tests for model configuration."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from context_service.config.models import ModelSpec, ModelsConfig, TierConfig


def _make_tier(**kwargs: object) -> TierConfig:
    defaults: dict[str, object] = dict(
        embeddings=ModelSpec(provider="ollama", model="nomic-embed-text", dimensions=768),
        reasoning=ModelSpec(provider="ollama", model="llama3"),
        fast=ModelSpec(provider="ollama", model="llama3"),
    )
    defaults.update(kwargs)
    return TierConfig(**defaults)  # type: ignore[arg-type]


def _minimal_config(**kwargs: object) -> ModelsConfig:
    defaults: dict[str, object] = dict(
        tier="economy",
        tiers={"economy": _make_tier()},
    )
    defaults.update(kwargs)
    return ModelsConfig(**defaults)  # type: ignore[arg-type]


class TestModelSpecUrl:
    def test_url_field_accepted(self) -> None:
        spec = ModelSpec(
            provider="tei",
            model="BAAI/bge-reranker-v2-m3",
            url="http://localhost:8082",
        )
        assert spec.url == "http://localhost:8082"

    def test_url_defaults_to_none(self) -> None:
        spec = ModelSpec(provider="ollama", model="nomic-embed-text")
        assert spec.url is None

    def test_url_can_be_set_to_none_explicitly(self) -> None:
        spec = ModelSpec(provider="tei", model="BAAI/bge-reranker-v2-m3", url=None)
        assert spec.url is None


class TestModelsConfigStandaloneTiers:
    def test_standalone_lite_accepted(self) -> None:
        cfg = _minimal_config(
            tier="standalone_lite",
            tiers={"standalone_lite": _make_tier()},
        )
        assert cfg.tier == "standalone_lite"

    def test_standalone_standard_accepted(self) -> None:
        cfg = _minimal_config(
            tier="standalone_standard",
            tiers={"standalone_standard": _make_tier()},
        )
        assert cfg.tier == "standalone_standard"

    def test_standalone_pro_accepted(self) -> None:
        cfg = _minimal_config(
            tier="standalone_pro",
            tiers={"standalone_pro": _make_tier()},
        )
        assert cfg.tier == "standalone_pro"

    def test_invalid_tier_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _minimal_config(tier="nonexistent_tier", tiers={"nonexistent_tier": _make_tier()})
