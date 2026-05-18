from pathlib import Path

import pytest

from context_service.mcp.tools import preset_registry
from context_service.mcp.tools.preset_registry import (
    Preset,
    get_preset,
    load_preset_config,
)


def test_loads_builtin_presets():
    cfg = load_preset_config()
    assert "coding" in cfg["presets"]
    assert "b2b-ops" in cfg["presets"]


def test_get_preset_returns_typed_preset():
    p = get_preset("coding")
    assert isinstance(p, Preset)
    assert p.name == "coding"
    assert p.namespace == "coding"
    assert p.onboarding_skill == "coding:onboarding"
    assert isinstance(p.param_overrides, dict)
    assert p.param_overrides == {"default_recall_top_k": 15}


def test_unknown_preset_raises_keyerror():
    with pytest.raises(KeyError):
        get_preset("does-not-exist")


def test_malformed_config_does_not_poison_cache(reset_preset_cache, tmp_path, monkeypatch):
    """A malformed config must raise on every call, not cache a bad value."""
    bad = tmp_path / "bad.yaml"
    bad.write_text("just a string, not a mapping\n")
    monkeypatch.setattr(preset_registry, "_CONFIG_PATH", bad)

    with pytest.raises(ValueError, match="missing 'presets' key"):
        load_preset_config()
    # Second call must still raise; a poisoned cache would return the bad value.
    with pytest.raises(ValueError, match="missing 'presets' key"):
        load_preset_config()

    # After pointing back at a valid config, loading succeeds.
    monkeypatch.setattr(
        preset_registry,
        "_CONFIG_PATH",
        Path(preset_registry.__file__).parent.parent.parent / "config" / "mcp_presets.yaml",
    )
    preset_registry._cached_config = None
    cfg = load_preset_config()
    assert "coding" in cfg["presets"]
