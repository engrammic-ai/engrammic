"""Tests for reranking settings."""

from __future__ import annotations


class TestRerankingSettings:
    def test_reranking_settings_defaults(self) -> None:
        from context_service.config.settings import RerankingSettings

        settings = RerankingSettings()
        assert settings.enabled is True
        assert settings.expand_hard_queries is True
        assert settings.expansion_cache_ttl_days == 7

    def test_reranking_settings_in_main_settings(self) -> None:
        from context_service.config.settings import Settings

        settings = Settings()
        assert hasattr(settings, "reranking")
        assert settings.reranking.enabled is True
