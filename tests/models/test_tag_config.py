"""Tests for SiloTagConfig model."""

import uuid

from context_service.models.tag_config import DEFAULT_SETTINGS, SiloTagConfig


def test_silo_tag_config_defaults():
    config = SiloTagConfig(
        silo_id=uuid.uuid4(),
        core_tags=[],
        dynamic_tags=[],
        settings=DEFAULT_SETTINGS.copy(),
        constraints={"hierarchy": {}, "layer_hints": {}, "mutual_exclusion": []},
    )
    assert config.core_tags == []
    assert config.dynamic_tags == []
    assert config.settings == DEFAULT_SETTINGS
    assert config.constraints == {"hierarchy": {}, "layer_hints": {}, "mutual_exclusion": []}


def test_default_settings_has_required_keys():
    assert "min_tags" in DEFAULT_SETTINGS
    assert "max_tags" in DEFAULT_SETTINGS
    assert "cosine_threshold" in DEFAULT_SETTINGS
    assert "promotion_threshold" in DEFAULT_SETTINGS
    assert "demotion_days" in DEFAULT_SETTINGS
    assert "synonym_threshold" in DEFAULT_SETTINGS


def test_all_tags_combines_core_and_dynamic():
    config = SiloTagConfig(
        silo_id=uuid.uuid4(),
        core_tags=["core1", "core2"],
        dynamic_tags=["dyn1", "core1"],
    )
    all_tags = config.all_tags()
    assert set(all_tags) == {"core1", "core2", "dyn1"}
