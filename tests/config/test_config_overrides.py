"""Tests for host-mounted config override resolution.

Self-hosters mount a directory of override YAML files and point
ENGRAMMIC_CONFIG_DIR at it. Files present there shadow the copies baked into
the image; anything absent falls back to the default. See paths.resolve_config_file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from context_service.config.paths import resolve_config_file


def test_no_override_env_returns_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENGRAMMIC_CONFIG_DIR", raising=False)
    default = Path("/app/config/models.yaml")
    assert resolve_config_file("models.yaml", default) == default


def test_override_dir_set_but_file_absent_returns_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ENGRAMMIC_CONFIG_DIR", str(tmp_path))
    default = Path("/app/config/models.yaml")
    assert resolve_config_file("models.yaml", default) == default


def test_override_file_present_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    override = tmp_path / "models.yaml"
    override.write_text("tier: balanced\n")
    monkeypatch.setenv("ENGRAMMIC_CONFIG_DIR", str(tmp_path))
    default = Path("/app/config/models.yaml")
    assert resolve_config_file("models.yaml", default) == override


def test_override_matches_by_bare_filename(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # The default may live in a different directory (src-level YAMLs); the
    # override is matched by bare filename regardless of the default's location.
    override = tmp_path / "tags.yaml"
    override.write_text("defaults: {}\n")
    monkeypatch.setenv("ENGRAMMIC_CONFIG_DIR", str(tmp_path))
    default = Path("/app/src/context_service/config/tags.yaml")
    assert resolve_config_file("tags.yaml", default) == override


def test_override_dir_pointing_at_missing_path_returns_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ENGRAMMIC_CONFIG_DIR", str(tmp_path / "does-not-exist"))
    default = Path("/app/config/models.yaml")
    assert resolve_config_file("models.yaml", default) == default
