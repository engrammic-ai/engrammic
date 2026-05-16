"""ICP preset registry - loads preset definitions from YAML.

Mirrors the loader pattern in mcp/tools/registry.py. The silo->preset binding
is NOT here; it lives in the Postgres silo_config.preset column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "mcp_presets.yaml"
_cached_config: dict[str, Any] | None = None


class Preset(BaseModel):
    """A resolved ICP preset."""

    name: str
    namespace: str
    onboarding_skill: str
    param_overrides: dict[str, Any] = Field(default_factory=dict)


def load_preset_config() -> dict[str, Any]:
    """Load preset configuration from YAML. Cached after first call.

    Raises on malformed yaml so a bad config fails fast at boot, matching
    mcp_tools.yaml behavior.
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    with open(_CONFIG_PATH) as f:
        _cached_config = yaml.safe_load(f)

    if not isinstance(_cached_config, dict) or "presets" not in _cached_config:
        raise ValueError(f"Malformed {_CONFIG_PATH}: missing 'presets' key")

    logger.info("mcp_preset_config_loaded", path=str(_CONFIG_PATH))
    return _cached_config


def get_preset(name: str) -> Preset:
    """Return the typed Preset for `name`. Raises KeyError if unknown."""
    config = load_preset_config()
    presets = config["presets"]
    if name not in presets:
        raise KeyError(name)
    raw = presets[name]
    return Preset(
        name=name,
        namespace=raw["namespace"],
        onboarding_skill=raw["onboarding_skill"],
        param_overrides=raw.get("param_overrides") or {},
    )
