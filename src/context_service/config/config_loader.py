"""YAML configuration loader for prompt templates and schemas.

Loads config files from the config/ directory at project root.
Configs are cached after first load.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from context_service.config.paths import config_dir

CONFIG_DIR: Path = config_dir()

# Environment variable overrides for specific configs
_ENV_OVERRIDES: dict[str, dict[str, str]] = {
    "embeddings": {
        "model": "EMBEDDING_MODEL",
        "dimensions": "EMBEDDING_DIMENSIONS",
    },
}


@lru_cache
def load_config(name: str) -> dict[str, Any]:
    """Load a YAML config file by name.

    Supports environment variable overrides for specific configs.
    See _ENV_OVERRIDES for supported overrides.

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

    # Apply environment variable overrides
    if name in _ENV_OVERRIDES:
        for key, env_var in _ENV_OVERRIDES[name].items():
            env_value = os.environ.get(env_var)
            if env_value is not None:
                # Convert to int for dimensions
                if key == "dimensions":
                    config[key] = int(env_value)
                else:
                    config[key] = env_value

    return config
