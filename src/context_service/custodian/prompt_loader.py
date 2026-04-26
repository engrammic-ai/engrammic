"""Cached YAML prompt loader with ``string.Template.safe_substitute`` rendering.

Prompts live under ``config/prompts/custodian/*.yaml``. Each file has a
``system_prompt`` key (the template) and optionally a ``lenses`` list naming
shared fragments under ``lenses/<name>.yaml``. Lens fragments expose a
``text`` key and are rendered first (with the same variables), then their
resolved text is substituted back into the main template as
``${<lens_name>}``.

The loader caches parsed YAML per-path; rendering cost is a couple of
``Template.safe_substitute`` calls per invocation.
"""

from __future__ import annotations

from functools import cache
from string import Template
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from pathlib import Path


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Prompt YAML at {path} must be a mapping, got {type(data).__name__}")
    return data


def load_prompt(prompt_path: Path, **vars: Any) -> str:
    """Render a prompt YAML template with the given variables.

    Lens fragments are resolved first so the main template sees each lens as
    a single ``${lens_name}`` variable already substituted.
    """
    data = _load_yaml(prompt_path)
    lenses_dir = prompt_path.parent / "lenses"
    lens_vars: dict[str, str] = {}
    for lens_name in data.get("lenses", []) or []:
        lens_data = _load_yaml(lenses_dir / f"{lens_name}.yaml")
        lens_text = lens_data.get("text", "")
        lens_vars[lens_name] = Template(lens_text).safe_substitute(**vars)
    template = Template(data["system_prompt"])
    return template.safe_substitute(**vars, **lens_vars)


def clear_cache() -> None:
    """Drop the YAML cache (used by hot-reload and tests)."""
    _load_yaml.cache_clear()


__all__ = ["clear_cache", "load_prompt"]
