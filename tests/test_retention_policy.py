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
