"""Startup config validation.

Validates config at startup and fails fast with actionable errors.
"""

from __future__ import annotations

import os

from context_service.config.logging import get_logger
from context_service.config.settings import get_settings

logger = get_logger(__name__)


class ConfigurationError(Exception):
    """Raised when config validation fails."""


def _has_adc() -> bool:
    """Check if Application Default Credentials are available."""
    try:
        import google.auth

        google.auth.default()
        return True
    except Exception:
        return False


def validate_config() -> None:
    """Validate config at startup. Fail fast with actionable errors."""
    settings = get_settings()
    tier = settings.models.tier
    active = settings.models.tiers[tier]
    errors: list[str] = []
    warnings: list[str] = []

    legacy_vars = {
        "LLM_MODEL": "Use MODELS__TIER or MODELS__OVERRIDES__REASONING__MODEL",
        "LLM_API_KEY": "Use provider-specific key (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)",
        "LITELLM_EMBEDDING_MODEL": "Use MODELS__TIER to select embedding model",
        "EMBEDDING_PROVIDER": "Use MODELS__TIER to select embedding provider",
    }
    for var, hint in legacy_vars.items():
        if os.environ.get(var):
            warnings.append(f"{var} is set but unused. {hint}")

    if active.embeddings.provider == "tei" and not settings.tei_url:
        errors.append("Tier uses TEI embeddings but TEI_URL is not set")

    if active.reasoning.provider == "ollama" and not any(
        os.environ.get(v) for v in ["OLLAMA_URL", "OLLAMA_BASE_URL", "OLLAMA_API_BASE"]
    ):
        errors.append("Tier uses Ollama but no OLLAMA_URL/OLLAMA_BASE_URL set")

    if active.reasoning.provider == "vertex_ai":
        has_project = settings.vertex_project or settings.vertex_project_id
        if not (has_project or _has_adc()):
            errors.append(
                "Tier uses Vertex AI but no VERTEX_PROJECT or ADC credentials found"
            )

    if active.embeddings.provider == "vertex_ai":
        has_project = settings.vertex_project or settings.vertex_project_id
        if not (has_project or _has_adc()):
            errors.append(
                "Tier uses Vertex AI embeddings but no VERTEX_PROJECT or ADC credentials found"
            )

    for w in warnings:
        logger.warning("config_warning", msg=w)

    if errors:
        msg = "Config validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        logger.error("config_validation_failed", errors=errors)
        raise ConfigurationError(msg)

    logger.info("config_validated", tier=tier)
