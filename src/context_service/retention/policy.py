"""Retention policy configuration and threshold logic."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetentionPolicy(BaseModel):
    """Per-silo retention thresholds with sensible defaults."""

    ephemeral_max_age_hours: int = Field(default=24, ge=1)
    standard_max_age_days: int = Field(default=7, ge=1)
    standard_heat_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    durable_max_age_days: int = Field(default=30, ge=1)
    durable_heat_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    meta_observation_max_count: int = Field(default=100, ge=10)
    grace_period_days: int = Field(default=7, ge=1)
