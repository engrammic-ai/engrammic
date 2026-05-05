"""Tests for tag configuration loader."""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

import context_service.config.tags as tags_module


def _reset_cache() -> None:
    tags_module._cache = None


def test_get_tag_defaults_returns_expected_keys():
    _reset_cache()
    defaults = tags_module.get_tag_defaults()
    assert defaults["min_tags"] == 2
    assert defaults["max_tags"] == 5
    assert defaults["cosine_threshold"] == pytest.approx(0.4)
    assert defaults["promotion_threshold"] == 3
    assert defaults["demotion_days"] == 30
    assert defaults["synonym_threshold"] == pytest.approx(0.85)
    assert defaults["cache_ttl_seconds"] == 300


def test_get_tag_defaults_caches_result():
    _reset_cache()
    parsed = {
        "defaults": {
            "min_tags": 2,
            "max_tags": 5,
            "cosine_threshold": 0.4,
            "promotion_threshold": 3,
            "demotion_days": 30,
            "synonym_threshold": 0.85,
            "cache_ttl_seconds": 300,
        }
    }
    with patch("context_service.config.tags.yaml.safe_load", return_value=parsed) as mock_load:
        # Also patch read_text at the Path class level so the file isn't touched
        with patch("pathlib.Path.read_text", return_value=""):
            first = tags_module.get_tag_defaults()
            second = tags_module.get_tag_defaults()

    assert first is second
    mock_load.assert_called_once()
