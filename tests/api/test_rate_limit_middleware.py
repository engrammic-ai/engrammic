"""Tests for rate limit middleware."""

from __future__ import annotations


class TestRateLimitMiddleware:
    def test_skips_health_endpoint(self) -> None:
        """Verify health endpoint is not rate limited."""
        from context_service.api.middleware import SKIP_RATE_LIMIT_PATHS

        assert "/health" in SKIP_RATE_LIMIT_PATHS

    def test_skips_metrics_endpoint(self) -> None:
        """Verify metrics endpoint is not rate limited."""
        from context_service.api.middleware import SKIP_RATE_LIMIT_PATHS

        assert "/metrics" in SKIP_RATE_LIMIT_PATHS

    def test_skips_mcp_paths(self) -> None:
        """Verify MCP paths are not rate limited."""
        from context_service.api.middleware import SKIP_RATE_LIMIT_PATHS

        assert "/mcp" in SKIP_RATE_LIMIT_PATHS
        assert "/_mcp" in SKIP_RATE_LIMIT_PATHS
