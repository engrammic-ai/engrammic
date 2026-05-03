"""Unit tests for v1.4 Phase 4c: Multi-chain Sessions + Auto-close.

Covers:
- create_or_join_session writes the correct Cypher
- attach_chain_to_session links chain to session
- close_session creates cross-chain REFERENCES edges and marks session closed
- close_session with a single chain skips cross-chain REFERENCES
- session_timeout_minutes setting defaults to 30
- context_reason forwards session_id when provided
- context_reason creates a new session when session_id is omitted
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fakes.fake_graph_store import FakeGraphStore

# ---------------------------------------------------------------------------
# engine/sessions tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_or_join_session_writes_once() -> None:
    store = FakeGraphStore()
    from context_service.engine.sessions import create_or_join_session

    result = await create_or_join_session(store, "sess-1", "silo-1")

    assert result == "sess-1"
    assert len(store.write_log) == 1
    cypher, params = store.write_log[0]
    assert "ReasoningSession" in cypher
    assert params["session_id"] == "sess-1"
    assert params["silo_id"] == "silo-1"


@pytest.mark.asyncio
async def test_attach_chain_to_session_writes_edge() -> None:
    store = FakeGraphStore()
    from context_service.engine.sessions import attach_chain_to_session

    await attach_chain_to_session(store, "chain-1", "sess-1", "silo-1")

    assert len(store.write_log) == 1
    cypher, params = store.write_log[0]
    assert "PART_OF_SESSION" in cypher
    assert params["chain_id"] == "chain-1"
    assert params["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_close_session_multi_chain_creates_references() -> None:
    store = FakeGraphStore()
    # GET_SESSION_CHAINS returns 2 chains
    store.seed_query_result([
        {"chain_id": "chain-1", "status": "open", "compacted": False},
        {"chain_id": "chain-2", "status": "open", "compacted": False},
    ])
    # CREATE_CROSS_CHAIN_REFERENCES returns edges_created=1
    store.seed_write_result([{"edges_created": 1}])

    from context_service.engine.sessions import close_session

    edges = await close_session(store, "sess-1", "silo-1")

    assert edges == 1
    # Expect: one query (GET_SESSION_CHAINS) + two writes (REFERENCES + CLOSE)
    assert len(store.query_log) == 1
    assert len(store.write_log) == 2
    # Second write should close the session
    close_cypher, close_params = store.write_log[1]
    assert "closed" in close_cypher
    assert close_params["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_close_session_single_chain_skips_references() -> None:
    store = FakeGraphStore()
    store.seed_query_result([
        {"chain_id": "chain-1", "status": "open", "compacted": False},
    ])

    from context_service.engine.sessions import close_session

    edges = await close_session(store, "sess-1", "silo-1")

    assert edges == 0
    # One query + one write (only CLOSE, no REFERENCES)
    assert len(store.query_log) == 1
    assert len(store.write_log) == 1
    close_cypher, _ = store.write_log[0]
    assert "closed" in close_cypher


@pytest.mark.asyncio
async def test_close_session_empty_session() -> None:
    """Closing a session with no chains should still mark it closed."""
    store = FakeGraphStore()
    store.seed_query_result([])  # no chains

    from context_service.engine.sessions import close_session

    edges = await close_session(store, "sess-empty", "silo-1")

    assert edges == 0
    assert len(store.write_log) == 1


# ---------------------------------------------------------------------------
# Settings test
# ---------------------------------------------------------------------------


def test_session_timeout_minutes_default() -> None:
    from context_service.config.settings import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.session_timeout_minutes == 30


def test_session_timeout_minutes_override() -> None:
    from context_service.config.settings import Settings

    s = Settings(session_timeout_minutes=60, _env_file=None)  # type: ignore[call-arg]
    assert s.session_timeout_minutes == 60


# ---------------------------------------------------------------------------
# context_reason tool — session_id wiring
# ---------------------------------------------------------------------------

_SERVER_MOD = "context_service.mcp.server"
_SILO_MOD = "context_service.mcp.tools.context_reason"


def _make_auth(session_id: str | None = None, agent_id: str | None = None) -> MagicMock:
    auth = MagicMock()
    auth.org_id = "org-1"
    auth.session_id = session_id
    auth.agent_id = agent_id
    return auth


def _make_chain_result(chain_id: str = "chain-abc") -> MagicMock:
    import uuid

    result = MagicMock()
    result.chain_id = uuid.UUID(chain_id) if len(chain_id) == 36 else uuid.uuid4()
    return result


def _patches(auth: MagicMock, ctx_svc: MagicMock) -> list:
    """Return a list of patch context managers for the context_reason tool."""
    return [
        patch(f"{_SERVER_MOD}.get_mcp_auth_context", AsyncMock(return_value=auth)),
        patch(f"{_SERVER_MOD}.get_silo_service", return_value=MagicMock()),
        patch(f"{_SERVER_MOD}.get_context_service", return_value=ctx_svc),
        patch(f"{_SILO_MOD}.validate_silo_ownership", AsyncMock(return_value=None)),
        patch(f"{_SILO_MOD}.derive_silo_id", return_value="silo-1"),
    ]


@pytest.mark.asyncio
async def test_context_reason_uses_provided_session_id() -> None:
    from contextlib import ExitStack

    from context_service.mcp.tools.context_reason import _context_reason

    chain_result = _make_chain_result("00000000-0000-0000-0000-000000000001")
    mock_store = FakeGraphStore()
    ctx_svc = MagicMock()
    ctx_svc.graph_store = mock_store
    ctx_svc.reason = AsyncMock(return_value=chain_result)

    with ExitStack() as stack:
        for p in _patches(_make_auth(), ctx_svc):
            stack.enter_context(p)
        result = await _context_reason(
            silo_id="silo-1",
            steps=[{"step": 1, "reasoning": "because", "confidence": 0.9}],
            session_id="caller-session-99",
        )

    assert result["session_id"] == "caller-session-99"
    # create_or_join_session + attach_chain_to_session = 2 writes
    assert len(mock_store.write_log) == 2


@pytest.mark.asyncio
async def test_context_reason_creates_new_session_when_omitted() -> None:
    from contextlib import ExitStack

    from context_service.mcp.tools.context_reason import _context_reason

    chain_result = _make_chain_result("00000000-0000-0000-0000-000000000002")
    mock_store = FakeGraphStore()
    ctx_svc = MagicMock()
    ctx_svc.graph_store = mock_store
    ctx_svc.reason = AsyncMock(return_value=chain_result)

    with ExitStack() as stack:
        for p in _patches(_make_auth(), ctx_svc):
            stack.enter_context(p)
        result = await _context_reason(
            silo_id="silo-1",
            steps=[{"step": 1, "reasoning": "because", "confidence": 0.9}],
            # no session_id provided
        )

    # A uuid should have been auto-generated
    assert len(result["session_id"]) == 36
    assert result["session_id"] != ""


@pytest.mark.asyncio
async def test_context_reason_uses_auth_session_id_as_fallback() -> None:
    from contextlib import ExitStack

    from context_service.mcp.tools.context_reason import _context_reason

    chain_result = _make_chain_result("00000000-0000-0000-0000-000000000003")
    mock_store = FakeGraphStore()
    ctx_svc = MagicMock()
    ctx_svc.graph_store = mock_store
    ctx_svc.reason = AsyncMock(return_value=chain_result)

    auth = _make_auth(session_id="auth-session-42")

    with ExitStack() as stack:
        for p in _patches(auth, ctx_svc):
            stack.enter_context(p)
        result = await _context_reason(
            silo_id="silo-1",
            steps=[{"step": 1, "reasoning": "because", "confidence": 0.9}],
            # no explicit session_id; auth has one
        )

    assert result["session_id"] == "auth-session-42"


# ---------------------------------------------------------------------------
# db/queries content checks
# ---------------------------------------------------------------------------


def test_session_queries_exist() -> None:
    from context_service.db import queries

    for name in (
        "CREATE_REASONING_SESSION",
        "ATTACH_CHAIN_TO_SESSION",
        "GET_STALE_OPEN_SESSIONS",
        "GET_SESSION_CHAINS",
        "CLOSE_REASONING_SESSION",
        "CREATE_CROSS_CHAIN_REFERENCES",
    ):
        assert hasattr(queries, name), f"Missing query: {name}"
        query = getattr(queries, name)
        assert isinstance(query, str) and len(query) > 10
