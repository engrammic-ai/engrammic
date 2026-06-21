"""Tests for the memory REST endpoints (remember and recall)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_app(*, memgraph_store: object | None = None, silo_id: str = "test-silo") -> object:
    """Build a minimal FastAPI app with the memory router mounted."""
    from fastapi import FastAPI

    from context_service.api.routes._auth import get_authenticated_silo
    from context_service.api.routes.memory import router

    app = FastAPI()
    app.include_router(router)
    store_mock = memgraph_store or MagicMock()
    app.state.memgraph = store_mock
    app.state.memgraph_store = store_mock

    # Override auth to return test silo
    async def mock_auth() -> tuple[str, str | None]:
        return silo_id, "test-session"

    app.dependency_overrides[get_authenticated_silo] = mock_auth
    return app


def _make_app_no_memgraph() -> object:
    """Build a minimal FastAPI app without memgraph in app state."""
    from fastapi import FastAPI

    from context_service.api.routes._auth import get_authenticated_silo
    from context_service.api.routes.memory import router

    app = FastAPI()
    app.include_router(router)
    # Intentionally no app.state.memgraph

    async def mock_auth() -> tuple[str, str | None]:
        return "test-silo", "test-session"

    app.dependency_overrides[get_authenticated_silo] = mock_auth
    return app


# ---------------------------------------------------------------------------
# remember tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remember_success() -> None:
    """POST /api/v1/remember returns 200 with node_id on success."""
    node_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    mock_result = MagicMock()
    mock_result.node_id = node_id
    mock_result.created_at = created_at

    app = _make_app()

    with patch(
        "context_service.api.routes.memory.store_memory",
        new_callable=AsyncMock,
        return_value=(mock_result, []),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/remember",
            json={"content": "The sky is blue", "tags": ["observation"]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == str(node_id)
    assert "created_at" in data


# Auth validation tests removed - silo_id is now derived from verified Bearer token
# via get_authenticated_silo dependency, not from caller-supplied headers.


@pytest.mark.asyncio
async def test_remember_service_unavailable() -> None:
    """POST /api/v1/remember returns 503 when Memgraph is not in app state."""
    app = _make_app_no_memgraph()

    client = TestClient(app)
    response = client.post(
        "/api/v1/remember",
        json={"content": "Some content"},
    )

    assert response.status_code == 503


# ---------------------------------------------------------------------------
# recall tests
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="needs mock update for fusion retriever path")
@pytest.mark.asyncio
async def test_recall_success() -> None:
    """POST /api/v1/recall returns 200 with results on success."""
    node_id = uuid.uuid4()
    created_at = datetime.now(UTC)

    mock_result_item = MagicMock()
    mock_result_item.node_id = node_id
    mock_result_item.content = "The sky is blue"
    mock_result_item.layer = "memory"
    mock_result_item.confidence = 0.9
    mock_result_item.relevance_score = 0.85
    mock_result_item.tags = ["observation"]
    mock_result_item.created_at = created_at
    mock_result_item.summary = None

    mock_ctx_svc = AsyncMock()
    mock_ctx_svc.query = AsyncMock(return_value=[mock_result_item])

    app = _make_app()

    with patch(
        "context_service.api.routes.memory.get_context_service",
        return_value=mock_ctx_svc,
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/recall",
            json={"query": "sky color", "top_k": 5},
        )

    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["node_id"] == str(node_id)
    assert result["content"] == "The sky is blue"
    assert result["layer"] == "memory"


@pytest.mark.asyncio
async def test_recall_service_unavailable() -> None:
    """POST /api/v1/recall returns 503 when Memgraph is not in app state."""
    app = _make_app_no_memgraph()

    client = TestClient(app)
    response = client.post(
        "/api/v1/recall",
        json={"query": "sky color"},
    )

    assert response.status_code == 503
