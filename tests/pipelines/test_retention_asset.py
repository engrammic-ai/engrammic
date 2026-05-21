"""Tests for per-silo retention config resolution in the retention asset."""

from __future__ import annotations

from context_service.models.silo import RetentionOverrides, SiloConfig
from context_service.retention.policy import RetentionPolicy


def _make_settings(supersession_chain_max_length: int = 20) -> object:
    """Build a minimal Settings-like object with the required retention fields."""

    class _FakeSettings:
        retention_ephemeral_max_age_hours = 24
        retention_standard_max_age_days = 7
        retention_standard_heat_threshold = 0.3
        retention_durable_max_age_days = 30
        retention_durable_heat_threshold = 0.2
        retention_meta_observation_max_count = 100
        retention_grace_period_days = 7
        retention_supersession_chain_max_length = supersession_chain_max_length

        # Non-retention fields required by SiloConfig.resolve()
        heat_half_life_days = 7
        heat_read_weight = 1.0
        heat_write_weight = 0.5
        heat_dedup_window_seconds = 300

        class custodian:
            min_edge_confidence = 0.7

        supersession_confidence_threshold = 0.75
        belief_density_threshold = 3
        revision_cosine_threshold = 0.15
        validator_auto_synthesis_threshold = 0.7
        validator_proposal_threshold = 0.5
        forget_enabled = True
        forget_cancel_window_hours = 1
        forget_rate_limit_per_hour = 100

    return _FakeSettings()


class TestRetentionPolicyFromResolved:
    def test_global_default_used_when_no_silo_override(self) -> None:
        """SiloConfig with no overrides falls back to global settings."""
        settings = _make_settings(supersession_chain_max_length=20)
        resolved = SiloConfig().resolve(settings)  # type: ignore[arg-type]
        policy = RetentionPolicy.from_resolved(resolved)
        assert policy.supersession_chain_max_length == 20

    def test_silo_override_supersedes_global(self) -> None:
        """A silo with a custom supersession_chain_max_length uses that value."""
        settings = _make_settings(supersession_chain_max_length=20)
        silo_config = SiloConfig(
            retention=RetentionOverrides(supersession_chain_max_length=5)
        )
        resolved = silo_config.resolve(settings)  # type: ignore[arg-type]
        policy = RetentionPolicy.from_resolved(resolved)
        assert policy.supersession_chain_max_length == 5

    def test_silo_override_does_not_affect_other_fields(self) -> None:
        """Custom supersession_chain_max_length does not change other policy fields."""
        settings = _make_settings(supersession_chain_max_length=20)
        silo_config = SiloConfig(
            retention=RetentionOverrides(supersession_chain_max_length=10)
        )
        resolved = silo_config.resolve(settings)  # type: ignore[arg-type]
        policy = RetentionPolicy.from_resolved(resolved)

        assert policy.supersession_chain_max_length == 10
        assert policy.ephemeral_max_age_hours == 24
        assert policy.standard_max_age_days == 7
        assert policy.grace_period_days == 7

    def test_from_resolved_all_retention_fields_match(self) -> None:
        """from_resolved() maps every retention field from ResolvedSiloConfig."""
        settings = _make_settings(supersession_chain_max_length=15)
        silo_config = SiloConfig(
            retention=RetentionOverrides(
                ephemeral_max_age_hours=48,
                standard_max_age_days=14,
                standard_heat_threshold=0.5,
                durable_max_age_days=60,
                durable_heat_threshold=0.1,
                meta_observation_max_count=50,
                grace_period_days=3,
                supersession_chain_max_length=8,
            )
        )
        resolved = silo_config.resolve(settings)  # type: ignore[arg-type]
        policy = RetentionPolicy.from_resolved(resolved)

        assert policy.ephemeral_max_age_hours == 48
        assert policy.standard_max_age_days == 14
        assert policy.standard_heat_threshold == 0.5
        assert policy.durable_max_age_days == 60
        assert policy.durable_heat_threshold == 0.1
        assert policy.meta_observation_max_count == 50
        assert policy.grace_period_days == 3
        assert policy.supersession_chain_max_length == 8

    def test_from_settings_includes_supersession_chain_max_length(self) -> None:
        """from_settings() also populates supersession_chain_max_length."""
        settings = _make_settings(supersession_chain_max_length=25)
        policy = RetentionPolicy.from_settings(settings)  # type: ignore[arg-type]
        assert policy.supersession_chain_max_length == 25
