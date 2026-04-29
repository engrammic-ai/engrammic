"""Regression test for S-006 — /docs, /redoc, /openapi.json must be off
under environment=production. See codebase-review-2026-04-28.md.
"""

from __future__ import annotations

import pytest


def _build_app_with_env(monkeypatch: pytest.MonkeyPatch, env: str) -> object:
    from context_service.api.app import create_app
    from context_service.config.settings import get_settings

    real = get_settings()
    monkeypatch.setattr(real, "environment", env, raising=False)
    return create_app()


def test_docs_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app_with_env(monkeypatch, "production")
    assert app.docs_url is None  # type: ignore[attr-defined]
    assert app.redoc_url is None  # type: ignore[attr-defined]
    assert app.openapi_url is None  # type: ignore[attr-defined]


def test_docs_enabled_in_development(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _build_app_with_env(monkeypatch, "development")
    assert app.docs_url == "/docs"  # type: ignore[attr-defined]
    assert app.redoc_url == "/redoc"  # type: ignore[attr-defined]
    assert app.openapi_url == "/openapi.json"  # type: ignore[attr-defined]
