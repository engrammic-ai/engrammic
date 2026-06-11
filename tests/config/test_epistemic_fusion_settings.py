"""Tests for EpistemicFusionConfig (read-path epistemic fusion, sprint step 1)."""

from __future__ import annotations

from context_service.config.settings import EpistemicFusionConfig


class TestEpistemicFusionConfig:
    def test_defaults(self) -> None:
        cfg = EpistemicFusionConfig()
        assert cfg.enabled is True
        assert cfg.confidence_weight == 0.3
        assert cfg.conflict_penalty == 0.5

    def test_frozen(self) -> None:
        cfg = EpistemicFusionConfig()
        try:
            cfg.enabled = False  # type: ignore[misc]
            raised = False
        except Exception:
            raised = True
        assert raised

    def test_attached_to_settings(self) -> None:
        from context_service.config.settings import Settings

        assert "epistemic_fusion" in Settings.model_fields
