"""Tests for configurable threshold hot-reload behavior."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from context_service.config.settings import Settings


class TestThresholdHotReload:
    """Verify threshold functions read from settings at call time, not import time."""

    def test_belief_density_threshold_reads_from_settings(self) -> None:
        """_get_min_facts_for_belief should read from settings each call."""
        from context_service.engine.synthesis import _get_min_facts_for_belief

        default = _get_min_facts_for_belief()
        assert default == 3

        with patch("context_service.engine.synthesis.get_settings") as mock:
            mock.return_value = Settings(belief_density_threshold=5)
            assert _get_min_facts_for_belief() == 5

    def test_revision_threshold_reads_from_settings(self) -> None:
        """_get_revision_threshold should read from settings each call."""
        from context_service.engine.revision import _get_revision_threshold

        default = _get_revision_threshold()
        assert default == pytest.approx(0.15)

        with patch("context_service.engine.revision.get_settings") as mock:
            mock.return_value = Settings(revision_cosine_threshold=0.25)
            assert _get_revision_threshold() == pytest.approx(0.25)

    def test_compaction_threshold_reads_from_settings(self) -> None:
        """_get_inline_threshold should read from settings each call."""
        from context_service.engine.summarization import _get_inline_threshold

        default = _get_inline_threshold()
        assert default == 5

        with patch("context_service.engine.summarization.get_settings") as mock:
            mock.return_value = Settings(compaction_step_threshold=10)
            assert _get_inline_threshold() == 10


class TestThresholdDefaults:
    """Verify default threshold values match expected constants."""

    def test_belief_density_default(self) -> None:
        settings = Settings()
        assert settings.belief_density_threshold == 3

    def test_revision_cosine_default(self) -> None:
        settings = Settings()
        assert settings.revision_cosine_threshold == pytest.approx(0.15)

    def test_compaction_step_default(self) -> None:
        settings = Settings()
        assert settings.compaction_step_threshold == 5

    def test_pattern_min_frequency_default(self) -> None:
        settings = Settings()
        assert settings.pattern_min_frequency == 2
