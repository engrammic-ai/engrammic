"""Prompts for entity and relationship extraction.

System prompt and user template are loaded from provider-specific presets
(config/prompts.yaml). Schema is loaded from config/extraction.yaml.
"""

from typing import Any

import yaml

from context_service.config.config_loader import CONFIG_DIR, load_config
from context_service.config.settings import get_settings

_DEFAULT_PRESET = "gemini"


def _load_prompts_config() -> dict[str, Any]:
    path = CONFIG_DIR / "prompts.yaml"
    with path.open() as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def _get_extraction_preset() -> dict[str, str]:
    preset = get_settings().prompt_preset
    config = _load_prompts_config()
    extraction: dict[str, dict[str, str]] = config.get("extraction", {})
    if preset in extraction:
        return extraction[preset]
    return extraction[_DEFAULT_PRESET]


def get_extraction_system_prompt() -> str:
    """Get the extraction system prompt for the active LLM preset."""
    return _get_extraction_preset()["system_prompt"].rstrip()


def get_extraction_user_template() -> str:
    """Get the extraction user template for the active LLM preset."""
    return _get_extraction_preset()["user_template"].rstrip()


# Schema is provider-independent, stays in extraction.yaml
_config = load_config("extraction")
EXTRACTION_SCHEMA: dict[str, Any] = _config["schema"]

# Module-level constants for backward compatibility — reflect active preset at import time.
EXTRACTION_SYSTEM_PROMPT: str = _config["system_prompt"].rstrip()
EXTRACTION_USER_TEMPLATE: str = _config["user_template"].rstrip()

# Causal extraction gate
# ---------------------
# The causal_relationships field is always present in EXTRACTION_SCHEMA and in the prompts
# above, but the pipeline should only process and persist causal edges when the flag is on.
#
# In the extraction pipeline (pipelines/assets/__init__.py or extraction/service.py),
# gate causal edge creation with:
#
#   if get_settings().causal.extraction_enabled:
#       # parse result["causal_relationships"] and create CAUSES/CORROBORATES/PREVENTS edges
#
# When the flag is off, ignore any causal_relationships returned by the LLM.
# The flag is settings.causal.extraction_enabled (CausalConfig, default False).
