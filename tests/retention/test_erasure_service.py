"""Tests for ErasureService GDPR erasure with cascade and audit logging."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_store():
    store = AsyncMock()
    # Default: node found and deleted
    store.execute_query.return_value = []
    return store


@pytest.fixture
def mock_qdrant():
    return AsyncMock()


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def valid_node_id():
    return str(uuid.uuid4())


@pytest.mark.asyncio
async def test_basic_erasure_logs_to_audit_table(
    mock_store, mock_qdrant, mock_db_session, valid_node_id
):
    """Successful erasure writes an ErasureAuditLog entry with status 'completed'."""
    from context_service.retention.erasure_service import ErasureService

    # hard_delete_node internals: execute_query returns a result (node found)
    mock_store.execute_query.return_value = [{"id": valid_node_id}]

    with patch("context_service.retention.service.enqueue_failed_delete", new_callable=AsyncMock):
        service = ErasureService(
            store=mock_store,
            qdrant_store=mock_qdrant,
            db_session=mock_db_session,
        )
        result = await service.erase(
            node_ids=[valid_node_id],
            silo_id="silo-1",
            requester_type="user",
            requester_id="user-42",
        )

    assert result["status"] == "completed"
    assert result["erased_count"] == 1
    assert result["failed_count"] == 0
    assert valid_node_id in result["erased_ids"]
    assert "request_id" in result

    # Audit log was added and committed
    mock_db_session.add.assert_called_once()
    mock_db_session.commit.assert_called_once()

    # Inspect the ErasureAuditLog object passed to add()
    audit_log = mock_db_session.add.call_args[0][0]
    from context_service.models.postgres.audit import ErasureAuditLog

    assert isinstance(audit_log, ErasureAuditLog)
    assert audit_log.silo_id == "silo-1"
    assert audit_log.requester_type == "user"
    assert audit_log.requester_id == "user-42"
    assert audit_log.status == "completed"
    assert audit_log.cascade_count == 0
    assert audit_log.error_details is None


@pytest.mark.asyncio
async def test_cascade_finds_and_deletes_referencing_nodes(
    mock_store, mock_qdrant, mock_db_session
):
    """With cascade=True, referencing nodes are discovered and also erased."""
    from context_service.retention.erasure_service import ErasureService

    target_id = str(uuid.uuid4())
    ref_id = str(uuid.uuid4())

    # First call is FIND_REFERENCING_NODES (returns ref_id), subsequent calls are
    # for each hard_delete_node (returns a result row to confirm deletion).
    call_count = 0

    async def execute_query_side_effect(query, params):
        nonlocal call_count
        call_count += 1
        if "MATCH (n {silo_id" in query:
            # Cascade query: return one referencing node
            return [{"node_id": ref_id}]
        # hard_delete_node query
        return [{"id": params.get("id", "")}]

    mock_store.execute_query.side_effect = execute_query_side_effect

    with patch("context_service.retention.service.enqueue_failed_delete", new_callable=AsyncMock):
        service = ErasureService(
            store=mock_store,
            qdrant_store=mock_qdrant,
            db_session=mock_db_session,
        )
        result = await service.erase(
            node_ids=[target_id],
            silo_id="silo-1",
            requester_type="admin",
            cascade=True,
        )

    assert result["status"] == "completed"
    assert result["cascade_count"] == 1
    assert result["erased_count"] == 2
    assert target_id in result["erased_ids"]
    assert ref_id in result["erased_ids"]

    audit_log = mock_db_session.add.call_args[0][0]
    assert audit_log.cascade_count == 1


@pytest.mark.asyncio
async def test_partial_failure_status_when_some_nodes_fail(
    mock_store, mock_qdrant, mock_db_session
):
    """When some nodes succeed and others fail, status is 'partial'."""
    from context_service.retention.erasure_service import ErasureService

    good_id = str(uuid.uuid4())
    bad_id = str(uuid.uuid4())

    async def execute_query_side_effect(query, params):
        node_id = params.get("id", "")
        if node_id == good_id:
            return [{"id": good_id}]
        # bad_id: simulate node not found (empty result)
        return []

    mock_store.execute_query.side_effect = execute_query_side_effect

    with patch("context_service.retention.service.enqueue_failed_delete", new_callable=AsyncMock):
        service = ErasureService(
            store=mock_store,
            qdrant_store=mock_qdrant,
            db_session=mock_db_session,
        )
        result = await service.erase(
            node_ids=[good_id, bad_id],
            silo_id="silo-1",
            requester_type="system",
        )

    assert result["status"] == "partial"
    assert result["erased_count"] == 1
    assert result["failed_count"] == 1
    assert good_id in result["erased_ids"]
    assert bad_id in result["failed_ids"]

    audit_log = mock_db_session.add.call_args[0][0]
    assert audit_log.status == "partial"
    assert audit_log.error_details is not None
    assert bad_id in audit_log.error_details


@pytest.mark.asyncio
async def test_all_nodes_fail_status_is_failed(
    mock_store, mock_qdrant, mock_db_session, valid_node_id
):
    """When all nodes fail to erase, status is 'failed'."""
    from context_service.retention.erasure_service import ErasureService

    # Node not found: empty result
    mock_store.execute_query.return_value = []

    service = ErasureService(
        store=mock_store,
        qdrant_store=mock_qdrant,
        db_session=mock_db_session,
    )
    result = await service.erase(
        node_ids=[valid_node_id],
        silo_id="silo-1",
        requester_type="user",
    )

    assert result["status"] == "failed"
    assert result["erased_count"] == 0
    assert result["failed_count"] == 1

    audit_log = mock_db_session.add.call_args[0][0]
    assert audit_log.status == "failed"


@pytest.mark.asyncio
async def test_erasure_result_contains_request_id(
    mock_store, mock_qdrant, mock_db_session, valid_node_id
):
    """Result always includes a unique request_id."""
    from context_service.retention.erasure_service import ErasureService

    mock_store.execute_query.return_value = [{"id": valid_node_id}]

    with patch("context_service.retention.service.enqueue_failed_delete", new_callable=AsyncMock):
        service = ErasureService(
            store=mock_store,
            qdrant_store=mock_qdrant,
            db_session=mock_db_session,
        )
        result = await service.erase(
            node_ids=[valid_node_id],
            silo_id="silo-1",
            requester_type="admin",
        )

    request_id = result["request_id"]
    # Must be a valid UUID
    parsed = uuid.UUID(request_id)
    assert str(parsed) == request_id
