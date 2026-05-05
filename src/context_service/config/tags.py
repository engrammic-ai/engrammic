"""Tag configuration loader.

Loads tag defaults from tags.yaml once and caches the result for the
lifetime of the process.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_TAGS_YAML = Path(__file__).parent / "tags.yaml"

_cache: dict[str, Any] | None = None


def get_tag_defaults() -> dict[str, Any]:
    """Return the tag defaults section from tags.yaml.

    The file is read exactly once; subsequent calls return the cached result.
    """
    global _cache
    if _cache is None:
        raw = yaml.safe_load(_TAGS_YAML.read_text())
        _cache = raw["defaults"]
    return _cache
