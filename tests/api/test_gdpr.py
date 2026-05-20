"""Tests for the GDPR erasure REST endpoint."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_app(
    *,
    memgraph_store: object | None = None,
    qdrant_client: object | None = None,
    admin_api_key: str | None = None,
) -> object:
    """Build a minimal FastAPI app with the GDPR router mounted."""
    from fastapi import FastAPI

    from context_service.api.routes.gdpr import router

    app = FastAPI()
    app.include_router(router)

    # Attach state so the endpoint can access stores
    app.state.memgraph = memgraph_store or MagicMock()
    if qdrant_client is not None:
        app.state.qdrant = qdrant_client

    return app


def _patch_admin_key(key: str | None = None):
    """Patch _require_admin_key to be a no-op (bypasses auth for unit tests)."""
    return patch(
        "context_service.api.routes.gdpr._require_admin_key",
        return_value=None,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_erase_returns_200_on_success() -> None:
    """POST /gdpr/erase returns 200 with erasure result on success."""
    node_id = str(uuid.uuid4())
    silo_id = "silo-test"

    mock_result = {
        "request_id": str(uuid.uuid4()),
        "status": "completed",
        "erased_count": 1,
        "failed_count": 0,
        "cascade_count": 0,
        "erased_ids": [node_id],
        "failed_ids": [],
    }

    mock_service = AsyncMock()
    mock_service.erase.return_value = mock_result

    mock_engine = MagicMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session_cm)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)

    app = _make_app()

    with (
        _patch_admin_key(),
        patch(
            "context_service.api.routes.gdpr.ErasureService",
            return_value=mock_service,
        ),
        patch(
            "context_service.api.routes.gdpr.get_engine",
            return_value=mock_engine,
        ),
        patch(
            "context_service.api.routes.gdpr.AsyncSession",
            return_value=mock_session_cm,
        ),
        patch(
            "context_service.api.routes.gdpr.EngineQdrantStore",
            return_value=MagicMock(),
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/gdpr/erase",
            json={
                "node_ids": [node_id],
                "silo_id": silo_id,
                "requester_type": "admin",
                "requester_id": "admin-1",
                "cascade": False,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["erased_count"] == 1
    assert data["failed_count"] == 0
    assert node_id in data["erased_ids"]
    assert "request_id" in data


@pytest.mark.asyncio
async def test_erase_creates_audit_log_entry() -> None:
    """Erasure calls ErasureService.erase which writes an audit log entry."""
    node_id = str(uuid.uuid4())
    silo_id = "silo-audit"

    mock_db_session = AsyncMock()
    mock_db_session.add = MagicMock()
    mock_store = AsyncMock()

    # hard_delete_node: returns row indicating node was deleted
    mock_store.execute_query.return_value = [{"id": node_id}]

    mock_engine = MagicMock()
    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_db_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=None)

    app = _make_app(memgraph_store=mock_store)

    with (
        _patch_admin_key(),
        patch(
            "context_service.api.routes.gdpr.get_engine",
            return_value=mock_engine,
        ),
        patch(
            "context_service.api.routes.gdpr.AsyncSession",
            return_value=mock_session_cm,
        ),
        patch(
            "context_service.api.routes.gdpr.EngineQdrantStore",
            return_value=MagicMock(),
        ),
        patch(
            "context_service.retention.service.enqueue_failed_delete",
            new_callable=AsyncMock,
        ),
    ):
        client = TestClient(app)
        response = client.post(
            "/gdpr/erase",
            json={
                "node_ids": [node_id],
                "silo_id": silo_id,
                "requester_type": "user",
                "requester_id": "user-99",
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"

    # ErasureService writes an audit log via db_session.add + commit
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()

    audit_log = mock_db_session.add.call_args[0][0]
    from context_service.models.postgres.audit import ErasureAuditLog

    assert isinstance(audit_log, ErasureAuditLog)
    assert audit_log.silo_id == silo_id
    assert audit_log.requester_type == "user"
    assert audit_log.requester_id == "user-99"
    assert audit_log.status == "completed"


@pytest.mark.asyncio
async def test_erase_returns_400_for_empty_node_ids() -> None:
    """POST /gdpr/erase with empty node_ids returns 400."""
    app = _make_app()

    with _patch_admin_key():
        client = TestClient(app)
        response = client.post(
            "/gdpr/erase",
            json={
                "node_ids": [],
                "silo_id": "silo-1",
                "requester_type": "admin",
            },
        )

    assert response.status_code == 400
    assert "node_ids" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_erase_returns_503_when_memgraph_unavailable() -> None:
    """POST /gdpr/erase returns 503 when Memgraph is not in app state."""
    from fastapi import FastAPI

    from context_service.api.routes.gdpr import router

    app = FastAPI()
    app.include_router(router)
    # No app.state.memgraph set

    with _patch_admin_key():
        client = TestClient(app)
        response = client.post(
            "/gdpr/erase",
            json={
                "node_ids": [str(uuid.uuid4())],
                "silo_id": "silo-1",
                "requester_type": "admin",
            },
        )

    assert response.status_code == 503
