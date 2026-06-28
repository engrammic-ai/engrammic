"""Per-silo configuration overrides.

Each field is Optional. A None value means "use the global setting from
Settings". Resolved values are obtained via SiloConfig.resolve(), which
merges the per-silo override with the global fallback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from context_service.config.settings import Settings


class RetentionOverrides(BaseModel):
    """Per-silo retention policy overrides."""

    model_config = {"extra": "ignore"}

    ephemeral_max_age_hours: int | None = Field(
        default=None,
        ge=1,
        description="Hours before ephemeral nodes are eligible for pruning.",
    )
    standard_max_age_days: int | None = Field(
        default=None,
        ge=1,
        description="Days before standard nodes are eligible for pruning.",
    )
    standard_heat_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nodes below this heat score are eligible for standard pruning.",
    )
    durable_max_age_days: int | None = Field(
        default=None,
        ge=1,
        description="Days before durable nodes are eligible for pruning.",
    )
    durable_heat_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Nodes below this heat score are eligible for durable pruning.",
    )
    meta_observation_max_count: int | None = Field(
        default=None,
        ge=10,
        description="Maximum reflection Memory nodes retained per silo.",
    )
    grace_period_days: int | None = Field(
        default=None,
        ge=1,
        description="Days a pruning-eligible node is kept in a grace period.",
    )
    supersession_chain_max_length: int | None = Field(
        default=None,
        ge=3,
        description="Max nodes in a supersession chain before pruning.",
    )


class HeatDecayOverrides(BaseModel):
    """Per-silo heat decay rate overrides."""

    model_config = {"extra": "ignore"}

    half_life_days: int | None = Field(
        default=None,
        ge=1,
        description="Days for heat score to decay by half.",
    )
    read_weight: float | None = Field(
        default=None,
        ge=0.0,
        description="Heat increment per read event.",
    )
    write_weight: float | None = Field(
        default=None,
        ge=0.0,
        description="Heat increment per write event.",
    )
    dedup_window_seconds: int | None = Field(
        default=None,
        ge=0,
        description="Window in which duplicate heat events are suppressed.",
    )


class ValidatorOverrides(BaseModel):
    """Per-silo validator threshold overrides."""

    model_config = {"extra": "ignore"}

    min_edge_confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence for proposed edges; below this they are rejected.",
    )
    supersession_confidence_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Minimum confidence required for a claim to supersede an existing fact.",
    )
    belief_density_threshold: int | None = Field(
        default=None,
        ge=1,
        description="Minimum facts required to synthesise a Wisdom-layer belief.",
    )
    revision_cosine_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Cosine distance above which a belief centroid is considered stale.",
    )
    auto_synthesis_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence above which T3 auto-creates Belief from cluster.",
    )
    proposal_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Confidence above which (but below auto_synthesis) creates ProposedBelief.",
    )


class ForgetPolicyOverrides(BaseModel):
    """Per-silo forget policy overrides."""

    model_config = {"extra": "ignore"}

    cancel_window_hours: int | None = Field(
        default=None,
        ge=1,
        description="Hours within which a forget can be cancelled.",
    )
    rate_limit_per_hour: int | None = Field(
        default=None,
        ge=1,
        description="Max forget operations per hour.",
    )
    enabled: bool | None = Field(
        default=None,
        description="Whether forget is enabled for this silo.",
    )


class SiloConfig(BaseModel):
    """Per-silo configuration overrides stored in the Silo node's metadata.

    Fields default to None, meaning the global setting applies. Call
    resolve(settings) to get the effective value for any field.
    """

    model_config = {"extra": "ignore"}

    retention: RetentionOverrides = Field(default_factory=RetentionOverrides)
    heat_decay: HeatDecayOverrides = Field(default_factory=HeatDecayOverrides)
    validators: ValidatorOverrides = Field(default_factory=ValidatorOverrides)
    forget: ForgetPolicyOverrides = Field(default_factory=ForgetPolicyOverrides)

    def resolve(self, settings: Settings) -> ResolvedSiloConfig:
        """Merge per-silo overrides with global settings defaults.

        Returns a fully-resolved config with no Optional fields.
        """
        r = self.retention
        h = self.heat_decay
        v = self.validators
        f = self.forget

        return ResolvedSiloConfig(
            # Retention
            ephemeral_max_age_hours=(
                r.ephemeral_max_age_hours
                if r.ephemeral_max_age_hours is not None
                else settings.retention_ephemeral_max_age_hours
            ),
            standard_max_age_days=(
                r.standard_max_age_days
                if r.standard_max_age_days is not None
                else settings.retention_standard_max_age_days
            ),
            standard_heat_threshold=(
                r.standard_heat_threshold
                if r.standard_heat_threshold is not None
                else settings.retention_standard_heat_threshold
            ),
            durable_max_age_days=(
                r.durable_max_age_days
                if r.durable_max_age_days is not None
                else settings.retention_durable_max_age_days
            ),
            durable_heat_threshold=(
                r.durable_heat_threshold
                if r.durable_heat_threshold is not None
                else settings.retention_durable_heat_threshold
            ),
            meta_observation_max_count=(
                r.meta_observation_max_count
                if r.meta_observation_max_count is not None
                else settings.retention_meta_observation_max_count
            ),
            grace_period_days=(
                r.grace_period_days
                if r.grace_period_days is not None
                else settings.retention_grace_period_days
            ),
            # Heat decay
            heat_half_life_days=(
                h.half_life_days if h.half_life_days is not None else settings.heat_half_life_days
            ),
            heat_read_weight=(
                h.read_weight if h.read_weight is not None else settings.heat_read_weight
            ),
            heat_write_weight=(
                h.write_weight if h.write_weight is not None else settings.heat_write_weight
            ),
            heat_dedup_window_seconds=(
                h.dedup_window_seconds
                if h.dedup_window_seconds is not None
                else settings.heat_dedup_window_seconds
            ),
            # Validators
            min_edge_confidence=(
                v.min_edge_confidence
                if v.min_edge_confidence is not None
                else settings.custodian.min_edge_confidence
            ),
            supersession_confidence_threshold=(
                v.supersession_confidence_threshold
                if v.supersession_confidence_threshold is not None
                else settings.supersession_confidence_threshold
            ),
            belief_density_threshold=(
                v.belief_density_threshold
                if v.belief_density_threshold is not None
                else settings.belief_density_threshold
            ),
            revision_cosine_threshold=(
                v.revision_cosine_threshold
                if v.revision_cosine_threshold is not None
                else settings.revision_cosine_threshold
            ),
            auto_synthesis_threshold=(
                v.auto_synthesis_threshold
                if v.auto_synthesis_threshold is not None
                else settings.validator_auto_synthesis_threshold
            ),
            proposal_threshold=(
                v.proposal_threshold
                if v.proposal_threshold is not None
                else settings.validator_proposal_threshold
            ),
            supersession_chain_max_length=(
                r.supersession_chain_max_length
                if r.supersession_chain_max_length is not None
                else settings.retention_supersession_chain_max_length
            ),
            forget_cancel_window_hours=(
                f.cancel_window_hours
                if f.cancel_window_hours is not None
                else settings.forget_cancel_window_hours
            ),
            forget_rate_limit_per_hour=(
                f.rate_limit_per_hour
                if f.rate_limit_per_hour is not None
                else settings.forget_rate_limit_per_hour
            ),
            forget_enabled=(f.enabled if f.enabled is not None else settings.forget_enabled),
        )

    def to_metadata_dict(self) -> dict[str, Any]:
        """Serialise to a dict suitable for storing in a Silo node's metadata."""
        return self.model_dump(exclude_none=False)

    @classmethod
    def from_metadata_dict(cls, data: dict[str, Any]) -> SiloConfig:
        """Deserialise from a Silo node's metadata dict."""
        return cls.model_validate(data)


class ResolvedSiloConfig(BaseModel):
    """Fully-resolved silo config with no Optional fields.

    Produced by SiloConfig.resolve(settings). Use this when you need a
    concrete value to pass to a subsystem.
    """

    model_config = {"extra": "ignore"}

    # Retention
    ephemeral_max_age_hours: int
    standard_max_age_days: int
    standard_heat_threshold: float
    durable_max_age_days: int
    durable_heat_threshold: float
    meta_observation_max_count: int
    grace_period_days: int
    supersession_chain_max_length: int

    # Heat decay
    heat_half_life_days: int
    heat_read_weight: float
    heat_write_weight: float
    heat_dedup_window_seconds: int

    # Validators
    min_edge_confidence: float
    supersession_confidence_threshold: float
    belief_density_threshold: int
    revision_cosine_threshold: float
    auto_synthesis_threshold: float
    proposal_threshold: float

    # Forget policy
    forget_enabled: bool
    forget_cancel_window_hours: int
    forget_rate_limit_per_hour: int
