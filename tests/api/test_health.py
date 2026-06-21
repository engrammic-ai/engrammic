"""Tests for the health check endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_service.api.routes.health import router


def _make_app(*, license_info: object | None = None) -> FastAPI:
    """Build a minimal FastAPI app with the health router mounted."""
    app = FastAPI()
    app.include_router(router)

    # Attach required state
    mock_store = MagicMock()
    mock_store.health_check = AsyncMock(return_value=True)
    app.state.memgraph = mock_store
    app.state.memgraph_store = mock_store
    app.state.redis = mock_store
    app.state.qdrant = mock_store

    if license_info is not None:
        app.state.license_info = license_info

    return app


def _make_settings(*, llm_api_key: str | None = None) -> MagicMock:
    settings = MagicMock()
    settings.llm.api_key = llm_api_key
    return settings


def test_health_returns_200() -> None:
    """Health endpoint returns 200 with required fields."""
    app = _make_app()
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "services" in data


def test_health_includes_license_info() -> None:
    """Health endpoint includes license information."""
    app = _make_app()
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert "license" in data
    assert "sage_mode" in data
    assert data["sage_mode"] in ["active", "passive"]


def test_health_sage_mode_active_when_llm_key_present() -> None:
    """sage_mode is 'active' when LLM API key is configured."""
    app = _make_app()
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(llm_api_key="sk-test-key"),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["sage_mode"] == "active"


def test_health_sage_mode_passive_without_llm_key() -> None:
    """sage_mode is 'passive' when no LLM API key is configured."""
    app = _make_app()
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(llm_api_key=None),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["sage_mode"] == "passive"


def test_health_license_populated_from_app_state() -> None:
    """License field is populated when license_info is set in app state."""
    import time

    license_info = MagicMock()
    license_info.customer = "acme-corp"
    license_info.expires_at = time.time() + 86400 * 30
    license_info.days_remaining = 30

    app = _make_app(license_info=license_info)
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["license"] is not None
    assert data["license"]["valid"] is True
    assert data["license"]["customer"] == "acme-corp"
    assert data["license"]["days_remaining"] == 30
    assert data["license"]["expires_at"] is not None


def test_health_license_null_when_not_set() -> None:
    """License field is null when no license_info in app state."""
    app = _make_app()
    with (
        patch(
            "context_service.api.routes.health.get_settings",
            return_value=_make_settings(),
        ),
        patch(
            "context_service.api.routes.health._postgres_health_check",
            new=AsyncMock(return_value=True),
        ),
    ):
        client = TestClient(app)
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["license"] is None
