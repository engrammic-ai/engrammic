"""Tests for tiered rate limit configuration."""

from context_service.config.settings import EndpointLimits, RateLimitConfig, TierLimits


class TestEndpointLimits:
    def test_default_values(self) -> None:
        limits = EndpointLimits()
        assert limits.requests_per_minute == 60
        assert limits.requests_per_hour == 600


class TestTierLimits:
    def test_has_all_categories(self) -> None:
        tier = TierLimits()
        assert hasattr(tier, "mcp_write")
        assert hasattr(tier, "mcp_read")
        assert hasattr(tier, "admin")
        assert hasattr(tier, "rest")


class TestRateLimitConfig:
    def test_default_tiers_exist(self) -> None:
        config = RateLimitConfig()
        assert "free" in config.tiers
        assert "starter" in config.tiers
        assert "pro" in config.tiers
        assert "enterprise" in config.tiers

    def test_enabled_defaults_false(self) -> None:
        config = RateLimitConfig()
        assert config.enabled is False

    def test_default_tier_is_free(self) -> None:
        config = RateLimitConfig()
        assert config.default_tier == "free"

    def test_get_limits_for_tier(self) -> None:
        config = RateLimitConfig()
        limits = config.get_limits("pro")
        assert limits.mcp_write.requests_per_minute == 200

    def test_get_limits_unknown_tier_returns_default(self) -> None:
        config = RateLimitConfig()
        limits = config.get_limits("unknown")
        assert limits == config.tiers[config.default_tier]
