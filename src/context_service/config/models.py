"""Centralized model configuration.

Provides tier-based model selection (economy/balanced/premium) with
task-level overrides. Precedence (highest to lowest):
1. Postgres per-org/silo overrides
2. Environment variables (MODELS__TIER, MODELS__OVERRIDES__*)
3. config/models.yaml explicit overrides
4. config/models.yaml tier defaults
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from context_service.config.paths import config_dir


class ModelSpec(BaseModel):
    """Specification for a single model."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str
    model: str
    dimensions: int | None = None


class TierConfig(BaseModel):
    """Model assignments for a single tier."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    embeddings: ModelSpec
    reasoning: ModelSpec
    fast: ModelSpec


class ModelsConfig(BaseModel):
    """Central model configuration with tier presets."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    tier: Literal[
        "economy", "balanced", "premium", "hybrid", "self_hosted", "self_hosted_budget"
    ] = "balanced"
    vertex_location: str = "us-central1"
    vertex_project: str = ""
    tiers: dict[str, TierConfig]
    task_mapping: dict[str, str] = Field(default_factory=dict)
    overrides: dict[str, ModelSpec] = Field(default_factory=dict)

    def get_model(self, task: str) -> ModelSpec:
        """Resolve model for a task: override > tier mapping > default.

        Args:
            task: Task identifier (e.g., "summarization", "pattern_detection")

        Returns:
            ModelSpec for the resolved model.
        """
        if task in self.overrides:
            return self.overrides[task]
        tier_key = self.task_mapping.get(task, "fast")
        active_tier = self.tiers[self.tier]
        if tier_key == "reasoning":
            return active_tier.reasoning
        if tier_key == "embeddings":
            return active_tier.embeddings
        return active_tier.fast

    def get_embedding_model(self) -> ModelSpec:
        """Get the embedding model for the active tier."""
        return self.tiers[self.tier].embeddings

    @property
    def litellm_embedding_model(self) -> str:
        """Convenience for litellm format: provider/model."""
        spec = self.get_embedding_model()
        return f"{spec.provider}/{spec.model}"

    @property
    def embedding_dimensions(self) -> int:
        """Embedding dimensions for the active tier."""
        spec = self.get_embedding_model()
        return spec.dimensions or 768


def _load_models_yaml(path: Path) -> dict[str, Any]:
    """Load and parse models.yaml."""
    if not path.exists():
        raise FileNotFoundError(f"models.yaml not found at {path}")
    return yaml.safe_load(path.read_text()) or {}


@lru_cache(maxsize=1)
def load_models_config() -> ModelsConfig:
    """Load ModelsConfig from config/models.yaml.

    Environment variable MODELS__TIER overrides the tier from yaml.
    Cached after first call. Use clear_models_config_cache() to reload.
    """
    import os

    path = config_dir() / "models.yaml"
    data = _load_models_yaml(path)

    # Allow env var to override tier
    env_tier = os.environ.get("MODELS__TIER")
    if env_tier and env_tier in ("economy", "balanced", "premium"):
        data["tier"] = env_tier

    return ModelsConfig(**data)


def clear_models_config_cache() -> None:
    """Clear the cached ModelsConfig. Call before reload_settings()."""
    load_models_config.cache_clear()
