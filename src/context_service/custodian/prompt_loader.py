"""Cached YAML prompt loader with ``string.Template.safe_substitute`` rendering.

Prompts live under the repo's ``config/`` tree (today: ``prompts/custodian/*.yaml``,
with shared fragments under ``prompts/<consumer>/lenses/<name>.yaml``). Callers
pass a path relative to ``config/`` — the loader does not assume a particular
consumer subdirectory, so future agents (extraction, silo, etc.) can drop
their own prompts in ``prompts/<their_name>/`` without changing this module.

Each prompt YAML has a ``system_prompt`` key (the template) and optionally a
``lenses`` list naming shared fragments. Lens fragments expose a ``text`` key
and are rendered first with the same variables, then their resolved text is
substituted back into the main template as ``${<lens_name>}``. Lens lookup is
relative to the prompt's own directory: a prompt at
``prompts/custodian/fast_pass.yaml`` resolves the lens ``injection_defense`` to
``prompts/custodian/lenses/injection_defense.yaml``.

The loader caches parsed YAML per absolute path; rendering cost is a couple of
``Template.safe_substitute`` calls per invocation.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from string import Template
from typing import Any

import yaml

from context_service.config.paths import config_dir


@cache
def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Prompt YAML at {path} must be a mapping, got {type(data).__name__}")
    return data


def load_prompt(rel_path: str | Path, **vars: Any) -> str:
    """Render a prompt YAML template at ``config_dir() / rel_path``.

    Args:
        rel_path: Path to the prompt YAML, relative to the repo's ``config/``
            directory (e.g. ``"prompts/custodian/fast_pass.yaml"``). May be a
            string or ``Path``.
        **vars: Template variables for ``Template.safe_substitute``.

    Lens fragments named in the prompt's ``lenses`` list are resolved first,
    rendered with the same variables, and substituted back as ``${lens_name}``.
    """
    full_path = (config_dir() / rel_path).resolve()
    data = _load_yaml(full_path)
    lenses_dir = full_path.parent / "lenses"
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
