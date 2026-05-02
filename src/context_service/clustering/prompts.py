"""Prompts for cluster summary generation.

System prompt and user template are loaded from provider-specific presets
in config/prompts.yaml (clustering section) when available, falling back
to the top-level keys in config/clustering.yaml.
Schema and limits are always loaded from config/clustering.yaml.
"""

from typing import Any

import yaml

from context_service.config.config_loader import CONFIG_DIR, load_config
from context_service.config.settings import get_settings

_DEFAULT_PRESET = "gemini"


def _load_prompts_config() -> dict[str, Any]:
    path = CONFIG_DIR / "prompts.yaml"
    if not path.exists():
        return {}
    with path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    return data


def _get_clustering_preset() -> dict[str, str] | None:
    preset = get_settings().prompt_preset
    config = _load_prompts_config()
    clustering: dict[str, dict[str, str]] = config.get("clustering", {})
    if preset in clustering:
        return clustering[preset]
    if _DEFAULT_PRESET in clustering:
        return clustering[_DEFAULT_PRESET]
    return None


def get_clustering_system_prompt() -> str:
    """Get the clustering system prompt for the active LLM preset."""
    preset = _get_clustering_preset()
    if preset:
        return preset["system_prompt"].rstrip()
    result: str = _config["system_prompt"]
    return result.rstrip()


def get_clustering_user_template() -> str:
    """Get the clustering user template for the active LLM preset."""
    preset = _get_clustering_preset()
    if preset:
        return preset["user_template"].rstrip()
    result: str = _config["user_template"]
    return result.rstrip()


# Schema and limits are provider-independent, stay in clustering.yaml
_config = load_config("clustering")
CLUSTER_SUMMARY_SCHEMA: dict[str, Any] = _config["schema"]
MAX_MEMBERS_FOR_SUMMARY: int = _config["limits"]["max_members_for_summary"]
MAX_CONTENT_LENGTH: int = _config["limits"]["max_content_length"]
