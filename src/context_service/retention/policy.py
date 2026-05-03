"""Retention policy configuration and threshold logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from context_service.config.settings import Settings


class RetentionPolicy(BaseModel):
    """Per-silo retention thresholds with sensible defaults."""

    ephemeral_max_age_hours: int = Field(default=24, ge=1)
    standard_max_age_days: int = Field(default=7, ge=1)
    standard_heat_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    durable_max_age_days: int = Field(default=30, ge=1)
    durable_heat_threshold: float = Field(default=0.2, ge=0.0, le=1.0)
    meta_observation_max_count: int = Field(default=100, ge=10)
    grace_period_days: int = Field(default=7, ge=1)

    def is_eligible_for_tombstone(
        self,
        decay_class: str,
        created_at: datetime,
        heat_score: float,
        now: datetime | None = None,
    ) -> bool:
        """Check if a node is eligible for tombstoning based on policy."""
        if now is None:
            now = datetime.now(UTC)

        age = now - created_at

        if decay_class == "permanent":
            return False

        if decay_class == "ephemeral":
            return age >= timedelta(hours=self.ephemeral_max_age_hours)

        if decay_class == "standard":
            return (
                age >= timedelta(days=self.standard_max_age_days)
                and heat_score < self.standard_heat_threshold
            )

        if decay_class == "durable":
            return (
                age >= timedelta(days=self.durable_max_age_days)
                and heat_score < self.durable_heat_threshold
            )

        return False

    @classmethod
    def from_settings(cls, settings: "Settings") -> "RetentionPolicy":
        """Create RetentionPolicy from application settings."""
        return cls(
            ephemeral_max_age_hours=settings.retention_ephemeral_max_age_hours,
            standard_max_age_days=settings.retention_standard_max_age_days,
            standard_heat_threshold=settings.retention_standard_heat_threshold,
            durable_max_age_days=settings.retention_durable_max_age_days,
            durable_heat_threshold=settings.retention_durable_heat_threshold,
            meta_observation_max_count=settings.retention_meta_observation_max_count,
            grace_period_days=settings.retention_grace_period_days,
        )
