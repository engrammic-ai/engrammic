"""Heat diffusion configuration: Pydantic models and YAML loader.

Loads config/diffusion.yaml from the repo root. Both loaders are cached
via lru_cache after first load.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from context_service.config.paths import config_dir

_CONFIG_FILENAME = "diffusion.yaml"


def _find_config_file() -> Path | None:
    """Locate config/diffusion.yaml relative to the repo root.

    Returns:
        Path to the config file, or None if not found.
    """
    candidate = config_dir() / _CONFIG_FILENAME
    if candidate.is_file():
        return candidate
    return None


class DiffusionThresholds(BaseModel):
    """Heat level thresholds that control materialization depth."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    full: float = Field(default=0.66, ge=0.0, le=1.0, description="Full materialization threshold")
    warm: float = Field(default=0.33, ge=0.0, le=1.0, description="Warm materialization threshold")
    structure: float = Field(
        default=0.1, ge=0.0, le=1.0, description="Structure-only materialization threshold"
    )


class DiffusionConfig(BaseModel):
    """Configuration for the heat diffusion algorithm."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Master gate for heat diffusion")
    hot_threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum heat for a node to be considered hot"
    )
    hop_decay: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Multiplicative decay factor applied at each hop during BFS",
    )
    max_depth: int = Field(
        default=3, ge=1, description="Maximum BFS depth for diffusion propagation"
    )
    min_threshold: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description="Minimum propagated heat; nodes below this are pruned from the frontier",
    )
    max_hot_nodes: int = Field(
        default=200, ge=1, description="Maximum number of hot nodes tracked per diffusion run"
    )
    propagated_heat_decay: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Additional decay applied to heat as it propagates through an edge",
    )

    thresholds: DiffusionThresholds = Field(default_factory=DiffusionThresholds)
    edge_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "CONTRADICTS": 0.95,
            "SUPPORTS": 0.90,
            "DEPENDS_ON": 0.85,
            "CITES": 0.80,
            "CAUSES": 0.80,
            "DERIVES_FROM": 0.75,
            "CORROBORATES": 0.70,
            "PREVENTS": 0.70,
            "RELATED_TO": 0.40,
        },
        description="Per-edge-type weight multipliers for heat propagation",
    )

    def get_materialization_level(
        self, effective_heat: float
    ) -> Literal["FULL", "WARM", "STRUCTURE", "MINIMAL"]:
        """Return the materialization level for a given effective heat value.

        Args:
            effective_heat: Node's effective heat score in [0.0, 1.0].

        Returns:
            One of 'FULL', 'WARM', 'STRUCTURE', or 'MINIMAL'.
        """
        if effective_heat >= self.thresholds.full:
            return "FULL"
        if effective_heat >= self.thresholds.warm:
            return "WARM"
        if effective_heat >= self.thresholds.structure:
            return "STRUCTURE"
        return "MINIMAL"


class PrewarmConfig(BaseModel):
    """Configuration for the prewarm sweep."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    enabled: bool = Field(default=True, description="Enable prewarm sweep")
    weak_links_priority_boost: float = Field(
        default=1.5,
        ge=0.0,
        description="Priority multiplier applied to weak links during prewarm",
    )
    skip_minimal_pattern_detection: bool = Field(
        default=True,
        description="Skip pattern detection for nodes that would land in MINIMAL tier",
    )


@lru_cache(maxsize=1)
def load_diffusion_config() -> DiffusionConfig:
    """Load and return the DiffusionConfig from config/diffusion.yaml.

    Falls back to all defaults if the config file is not found. Cached
    after the first call.

    Returns:
        DiffusionConfig instance.
    """
    path = _find_config_file()
    if path is None:
        return DiffusionConfig()

    with path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    diffusion_data: dict[str, Any] = raw.get("diffusion", {})
    return DiffusionConfig(**diffusion_data)


@lru_cache(maxsize=1)
def load_prewarm_config() -> PrewarmConfig:
    """Load and return the PrewarmConfig from config/diffusion.yaml.

    Falls back to all defaults if the config file is not found. Cached
    after the first call.

    Returns:
        PrewarmConfig instance.
    """
    path = _find_config_file()
    if path is None:
        return PrewarmConfig()

    with path.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    prewarm_data: dict[str, Any] = raw.get("prewarm", {})
    return PrewarmConfig(**prewarm_data)
