"""Tests for heat diffusion configuration loading."""

from __future__ import annotations

import pytest

from context_service.config.diffusion import (
    DiffusionConfig,
    DiffusionThresholds,
    PrewarmConfig,
    load_diffusion_config,
    load_prewarm_config,
)


def test_load_diffusion_config_defaults():
    """Verify all default values load correctly from config/diffusion.yaml."""
    config = load_diffusion_config()

    assert isinstance(config, DiffusionConfig)
    assert config.enabled is True
    assert config.hot_threshold == pytest.approx(0.5)
    assert config.hop_decay == pytest.approx(0.7)
    assert config.max_depth == 3
    assert config.min_threshold == pytest.approx(0.01)
    assert config.max_hot_nodes == 200
    assert config.propagated_heat_decay == pytest.approx(0.8)

    # Thresholds
    assert isinstance(config.thresholds, DiffusionThresholds)
    assert config.thresholds.full == pytest.approx(0.66)
    assert config.thresholds.warm == pytest.approx(0.33)
    assert config.thresholds.structure == pytest.approx(0.1)

    # Edge weights
    assert config.edge_weights["CONTRADICTS"] == pytest.approx(0.95)
    assert config.edge_weights["SUPPORTS"] == pytest.approx(0.90)
    assert config.edge_weights["DEPENDS_ON"] == pytest.approx(0.85)
    assert config.edge_weights["CITES"] == pytest.approx(0.80)
    assert config.edge_weights["CAUSES"] == pytest.approx(0.80)
    assert config.edge_weights["DERIVES_FROM"] == pytest.approx(0.75)
    assert config.edge_weights["CORROBORATES"] == pytest.approx(0.70)
    assert config.edge_weights["PREVENTS"] == pytest.approx(0.70)
    assert config.edge_weights["RELATED_TO"] == pytest.approx(0.40)


def test_load_prewarm_config_defaults():
    """Verify prewarm config loads correctly."""
    config = load_prewarm_config()

    assert isinstance(config, PrewarmConfig)
    assert config.enabled is True
    assert config.weak_links_priority_boost == pytest.approx(1.5)
    assert config.skip_minimal_pattern_detection is True


def test_materialization_level():
    """Verify get_materialization_level returns correct level for each heat range."""
    config = load_diffusion_config()

    # Above full threshold (>= 0.66) -> FULL
    assert config.get_materialization_level(1.0) == "FULL"
    assert config.get_materialization_level(0.66) == "FULL"
    assert config.get_materialization_level(0.75) == "FULL"

    # Between warm and full (>= 0.33 and < 0.66) -> WARM
    assert config.get_materialization_level(0.33) == "WARM"
    assert config.get_materialization_level(0.5) == "WARM"
    assert config.get_materialization_level(0.65) == "WARM"

    # Between structure and warm (>= 0.1 and < 0.33) -> STRUCTURE
    assert config.get_materialization_level(0.1) == "STRUCTURE"
    assert config.get_materialization_level(0.2) == "STRUCTURE"
    assert config.get_materialization_level(0.32) == "STRUCTURE"

    # Below structure threshold (< 0.1) -> MINIMAL
    assert config.get_materialization_level(0.0) == "MINIMAL"
    assert config.get_materialization_level(0.05) == "MINIMAL"
    assert config.get_materialization_level(0.09) == "MINIMAL"


def test_load_diffusion_config_is_cached():
    """Verify load_diffusion_config returns the same object on repeated calls."""
    config1 = load_diffusion_config()
    config2 = load_diffusion_config()
    assert config1 is config2


def test_load_prewarm_config_is_cached():
    """Verify load_prewarm_config returns the same object on repeated calls."""
    config1 = load_prewarm_config()
    config2 = load_prewarm_config()
    assert config1 is config2
