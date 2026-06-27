"""Tests for POST /api/v1/batch/remember and POST /api/v1/batch/learn endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from context_service.api.routes._auth import get_authenticated_silo
from context_service.api.routes.batch import router

SILO_ID = "test-silo"


def _make_app(
    *,
    silo_id: str = SILO_ID,
    mock_ctx: object | None = None,
) -> FastAPI:
    """Build a minimal FastAPI app with the batch router mounted."""
    app = FastAPI()
    app.include_router(router)

    async def mock_auth() -> tuple[str, str | None]:
        return silo_id, "test-session"

    app.dependency_overrides[get_authenticated_silo] = mock_auth

    if mock_ctx is not None:
        _ctx_store = {"ctx": mock_ctx}

        def _get_ctx() -> object:
            return _ctx_store["ctx"]

        app.state.mock_ctx = _ctx_store
    return app


def _make_store_result(
    node_id: uuid.UUID | None = None,
) -> MagicMock:
    result = MagicMock()
    result.node_id = node_id or uuid.uuid4()
    result.created_at = datetime.now(UTC)
    return result


# ---------------------------------------------------------------------------
# Main endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_remember_creates_nodes() -> None:
    """POST /api/v1/batch/remember creates nodes and returns correct counts."""
    node_id_1 = uuid.uuid4()
    node_id_2 = uuid.uuid4()

    results = [_make_store_result(node_id_1), _make_store_result(node_id_2)]
    call_count = 0

    async def fake_store_memory(*args: object, **kwargs: object) -> tuple[MagicMock, list]:
        nonlocal call_count
        r = results[call_count]
        call_count += 1
        return r, []

    mock_graph = AsyncMock()
    mock_graph.query_document_ids = AsyncMock(return_value={})

    mock_embed_svc = MagicMock()
    mock_embed_svc.embed = AsyncMock(return_value=[[0.1, 0.2], [0.3, 0.4]])

    mock_ctx = MagicMock()
    mock_ctx.graph_store = mock_graph
    mock_ctx.embedding_client = mock_embed_svc

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.store_memory",
            side_effect=fake_store_memory,
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "context_service.api.routes.batch.batch_embed",
            new_callable=AsyncMock,
            return_value=[[0.1, 0.2], [0.3, 0.4]],
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={
                "items": [
                    {"content": "First observation", "document_id": "doc-1"},
                    {"content": "Second observation", "document_id": "doc-2"},
                ],
                "options": {"conflict_mode": "skip"},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 2
    assert data["skipped"] == 0
    assert data["failed"] == 0
    assert len(data["results"]) == 2
    assert "request_id" in data
    assert data["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_batch_remember_skips_duplicates() -> None:
    """Items with existing document_ids are skipped in default skip mode."""
    existing_node_id = str(uuid.uuid4())

    app = _make_app()

    mock_ctx = MagicMock()
    mock_ctx.graph_store = AsyncMock()
    mock_ctx.embedding_client = None

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={"dup-1": existing_node_id},
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={"items": [{"content": "test2", "document_id": "dup-1"}]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["skipped"] == 1
    assert data["created"] == 0
    assert data["failed"] == 0
    assert data["results"][0]["node_id"] == existing_node_id
    assert data["results"][0]["status"] == "skipped"


@pytest.mark.asyncio
async def test_batch_remember_error_mode_rejects_duplicates() -> None:
    """conflict_mode=error causes duplicate document_ids to count as failed."""
    app = _make_app()

    mock_ctx = MagicMock()
    mock_ctx.graph_store = AsyncMock()
    mock_ctx.embedding_client = None

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={"err-1": str(uuid.uuid4())},
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={
                "items": [{"content": "test2", "document_id": "err-1"}],
                "options": {"conflict_mode": "error"},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["failed"] == 1
    assert data["skipped"] == 0
    assert "Duplicate" in data["results"][0]["error"]


@pytest.mark.asyncio
async def test_batch_remember_context_service_unavailable() -> None:
    """Returns 503 when ContextService is not configured."""
    app = _make_app()

    with patch(
        "context_service.api.routes.batch.get_context_service",
        side_effect=RuntimeError("not configured"),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={"items": [{"content": "test"}]},
        )

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_batch_remember_no_items_returns_empty() -> None:
    """Empty items list returns zero counts immediately."""
    mock_ctx = MagicMock()
    mock_ctx.graph_store = AsyncMock()
    mock_ctx.embedding_client = None

    app = _make_app()

    with patch(
        "context_service.api.routes.batch.get_context_service",
        return_value=mock_ctx,
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={"items": []},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 0
    assert data["skipped"] == 0
    assert data["failed"] == 0
    assert data["results"] == []


@pytest.mark.asyncio
async def test_batch_remember_item_without_document_id() -> None:
    """Items without document_id skip dedup check and are created normally."""
    result = _make_store_result()

    mock_ctx = MagicMock()
    mock_ctx.graph_store = AsyncMock()
    mock_ctx.embedding_client = None

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.store_memory",
            new_callable=AsyncMock,
            return_value=(result, []),
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/remember",
            json={"items": [{"content": "no doc id here"}]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    assert data["results"][0]["status"] == "created"


# ---------------------------------------------------------------------------
# batch/learn tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_learn_creates_claims() -> None:
    """POST /api/v1/batch/learn creates claims and returns sage_deferred flag."""
    node_id = uuid.uuid4()
    result = _make_store_result(node_id)

    mock_graph = AsyncMock()
    mock_graph.query_document_ids = AsyncMock(return_value={})
    mock_graph.query_spo_pairs = AsyncMock(return_value={})

    mock_ctx = MagicMock()
    mock_ctx.graph_store = mock_graph
    mock_ctx.embedding_client = None

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.store_claim",
            new_callable=AsyncMock,
            return_value=(result, []),
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "context_service.api.routes.batch.detect_supersession",
            new_callable=AsyncMock,
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/learn",
            headers={"X-Bypass-SAGE": "true"},
            json={
                "items": [
                    {
                        "content": "User prefers dark mode",
                        "evidence": ["https://example.com/settings"],
                        "subject": "user",
                        "predicate": "prefers",
                        "object": "dark_mode",
                        "document_id": "claim-1",
                    },
                ],
                "options": {
                    "skip_evidence_validation": False,
                    "conflict_mode": "supersede",
                },
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    assert data["sage_deferred"] is True
    assert data["results"][0]["status"] == "created"


@pytest.mark.asyncio
async def test_batch_learn_skip_evidence_validation_requires_admin_override() -> None:
    """skip_evidence_validation without X-Admin-Override returns 403."""
    mock_ctx = MagicMock()
    mock_ctx.graph_store = AsyncMock()
    mock_ctx.embedding_client = None

    app = _make_app()

    with patch(
        "context_service.api.routes.batch.get_context_service",
        return_value=mock_ctx,
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/learn",
            json={
                "items": [{"content": "test", "evidence": ["https://example.com"]}],
                "options": {"skip_evidence_validation": True},
            },
        )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_batch_learn_skip_evidence_validation_with_admin_override() -> None:
    """skip_evidence_validation with X-Admin-Override: true is accepted."""
    node_id = uuid.uuid4()
    result = _make_store_result(node_id)

    mock_graph = AsyncMock()
    mock_graph.query_document_ids = AsyncMock(return_value={})
    mock_graph.query_spo_pairs = AsyncMock(return_value={})

    mock_ctx = MagicMock()
    mock_ctx.graph_store = mock_graph
    mock_ctx.embedding_client = None

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.store_claim",
            new_callable=AsyncMock,
            return_value=(result, []),
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "context_service.api.routes.batch.detect_supersession",
            new_callable=AsyncMock,
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/learn",
            headers={"X-Admin-Override": "true"},
            json={
                "items": [{"content": "test claim", "evidence": ["https://example.com"]}],
                "options": {"skip_evidence_validation": True},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1


@pytest.mark.asyncio
async def test_batch_learn_supersession_value_error_returns_400() -> None:
    """ValueError from detect_supersession returns HTTP 400."""
    mock_graph = AsyncMock()
    mock_graph.query_document_ids = AsyncMock(return_value={})
    mock_graph.query_spo_pairs = AsyncMock(return_value={})

    mock_ctx = MagicMock()
    mock_ctx.graph_store = mock_graph
    mock_ctx.embedding_client = None

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "context_service.api.routes.batch.detect_supersession",
            new_callable=AsyncMock,
            side_effect=ValueError("SPO entry limit exceeded"),
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/learn",
            json={
                "items": [
                    {
                        "content": "test",
                        "evidence": ["https://example.com"],
                        "subject": "user",
                        "predicate": "prefers",
                        "object": "light_mode",
                    }
                ],
            },
        )

    assert response.status_code == 400
    assert "SPO entry limit exceeded" in response.json()["detail"]


@pytest.mark.asyncio
async def test_batch_learn_skips_duplicates() -> None:
    """Items with existing document_ids are skipped."""
    existing_node_id = str(uuid.uuid4())

    mock_graph = AsyncMock()
    mock_graph.query_document_ids = AsyncMock(return_value={})
    mock_graph.query_spo_pairs = AsyncMock(return_value={})

    mock_ctx = MagicMock()
    mock_ctx.graph_store = mock_graph
    mock_ctx.embedding_client = None

    app = _make_app()

    with (
        patch(
            "context_service.api.routes.batch.get_context_service",
            return_value=mock_ctx,
        ),
        patch(
            "context_service.api.routes.batch.dedup_check",
            new_callable=AsyncMock,
            return_value={"dup-claim-1": existing_node_id},
        ),
        patch(
            "context_service.api.routes.batch.detect_supersession",
            new_callable=AsyncMock,
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/api/v1/batch/learn",
            json={
                "items": [
                    {
                        "content": "duplicate claim",
                        "evidence": ["https://example.com"],
                        "document_id": "dup-claim-1",
                    }
                ],
                "options": {"conflict_mode": "skip"},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["skipped"] == 1
    assert data["created"] == 0
    assert data["results"][0]["status"] == "skipped"
    assert data["results"][0]["node_id"] == existing_node_id
