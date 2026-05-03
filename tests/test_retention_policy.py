from datetime import UTC, datetime, timedelta

from context_service.retention.policy import RetentionPolicy


def test_retention_policy_defaults():
    policy = RetentionPolicy()
    assert policy.ephemeral_max_age_hours == 24
    assert policy.standard_max_age_days == 7
    assert policy.standard_heat_threshold == 0.3
    assert policy.durable_max_age_days == 30
    assert policy.durable_heat_threshold == 0.2
    assert policy.meta_observation_max_count == 100
    assert policy.grace_period_days == 7


def test_ephemeral_eligible_after_24h():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_25h_ago = now - timedelta(hours=25)

    assert policy.is_eligible_for_tombstone(
        decay_class="ephemeral",
        created_at=created_25h_ago,
        heat_score=0.9,
        now=now,
    ) is True


def test_ephemeral_not_eligible_before_24h():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_23h_ago = now - timedelta(hours=23)

    assert policy.is_eligible_for_tombstone(
        decay_class="ephemeral",
        created_at=created_23h_ago,
        heat_score=0.1,
        now=now,
    ) is False


def test_standard_eligible_low_heat_old():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_8d_ago = now - timedelta(days=8)

    assert policy.is_eligible_for_tombstone(
        decay_class="standard",
        created_at=created_8d_ago,
        heat_score=0.2,
        now=now,
    ) is True


def test_standard_not_eligible_high_heat():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_8d_ago = now - timedelta(days=8)

    assert policy.is_eligible_for_tombstone(
        decay_class="standard",
        created_at=created_8d_ago,
        heat_score=0.5,
        now=now,
    ) is False


def test_permanent_never_eligible():
    policy = RetentionPolicy()
    now = datetime.now(UTC)
    created_1y_ago = now - timedelta(days=365)

    assert policy.is_eligible_for_tombstone(
        decay_class="permanent",
        created_at=created_1y_ago,
        heat_score=0.0,
        now=now,
    ) is False
