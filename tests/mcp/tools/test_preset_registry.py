import pytest

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


def test_unknown_preset_raises_keyerror():
    with pytest.raises(KeyError):
        get_preset("does-not-exist")
