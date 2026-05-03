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


# Schema is provider-independent, stays in extraction.yaml.
# Loaded lazily so import does not force config I/O at startup.
_extraction_schema_cache: dict[str, Any] | None = None


def get_extraction_schema() -> dict[str, Any]:
    """Get the extraction JSON schema (provider-independent)."""
    global _extraction_schema_cache
    if _extraction_schema_cache is None:
        _extraction_schema_cache = load_config("extraction")["schema"]
    return _extraction_schema_cache


# EXTRACTION_SCHEMA is a module-level alias kept only for callers that import it
# directly.  Prefer get_extraction_schema() in new code so the schema is not
# evaluated at import time.
def __getattr__(name: str) -> Any:
    if name == "EXTRACTION_SCHEMA":
        return get_extraction_schema()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
