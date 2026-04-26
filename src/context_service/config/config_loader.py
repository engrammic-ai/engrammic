"""YAML configuration loader for prompt templates and schemas.

Loads config files from the config/ directory at project root.
Configs are cached after first load.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "config"


@lru_cache
def load_config(name: str) -> dict[str, Any]:
    """Load a YAML config file by name.

    Args:
        name: Config file name without extension (e.g. "extraction", "clustering").

    Returns:
        Parsed config dictionary.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
    """
    path = CONFIG_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open() as f:
        config: dict[str, Any] = yaml.safe_load(f)

    return config
