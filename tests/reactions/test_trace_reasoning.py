"""Tests for TX7 TRACE handler (trace_reasoning_task).

The handler uses lazy imports for heavy optional deps (mcp.server, db.postgres, etc.)
that aren't available in the unit-test environment. We inject minimal stubs into
sys.modules before registering tasks so the handler body can be exercised without
those deps being installed.
"""

from __future__ import annotations

import sys
import types
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.reactions.events import ReactionEventType


# ---------------------------------------------------------------------------
# sys.modules stubs
# ---------------------------------------------------------------------------

def _ensure_stub(name: str) -> types.ModuleType:
    """Return the existing module or create and register an empty stub."""
    if name not in sys.modules:
        parts = name.split(".")
        # ensure parent packages exist
        for i in range(1, len(parts)):
            parent = ".".join(parts[:i])
            if parent not in sys.modules:
                sys.modules[parent] = types.ModuleType(parent)
        mod = types.ModuleType(name)
        sys.modules[name] = mod
        # attach to parent
        parent_mod = sys.modules[".".join(parts[:-1])]
        setattr(parent_mod, parts[-1], mod)
    return sys.modules[name]


def _inject_all_stubs(mock_ctx_svc: MagicMock, mock_pg_session: AsyncMock | None = None) -> None:
    """Inject stubs for all modules the handler lazily imports."""
    # context_service.mcp.server - get_context_service
    server_mod = _ensure_stub("context_service.mcp.server")
    server_mod.get_context_service = MagicMock(return_value=mock_ctx_svc)  # type: ignore[attr-defined]

    # context_service.db.postgres - get_session
    db_pg_mod = _ensure_stub("context_service.db.postgres")
    if mock_pg_session is not None:
        db_pg_mod.get_session = MagicMock(return_value=mock_pg_session)  # type: ignore[attr-defined]
    elif not hasattr(db_pg_mod, "get_session"):
        db_pg_mod.get_session = MagicMock(return_value=AsyncMock())  # type: ignore[attr-defined]

    # context_service.db.queries - GET_WORKING_HYPOTHESES_FOR_SESSION
    db_q_mod = _ensure_stub("context_service.db.queries")
    if not hasattr(db_q_mod, "GET_WORKING_HYPOTHESES_FOR_SESSION"):
        db_q_mod.GET_WORKING_HYPOTHESES_FOR_SESSION = "STUB_QUERY"  # type: ignore[attr-defined]

    # context_service.engine.models - BinaryEdge
    eng_mod = _ensure_stub("context_service.engine.models")
    if not hasattr(eng_mod, "BinaryEdge"):

        class _BinaryEdge:
            def __init__(self, **kwargs: Any) -> None:
                self.__dict__.update(kwargs)

        eng_mod.BinaryEdge = _BinaryEdge  # type: ignore[attr-defined]

    # context_service.models.postgres.reasoning - ReasoningChainSteps
    rcs_mod = _ensure_stub("context_service.models.postgres.reasoning")
    if not hasattr(rcs_mod, "ReasoningChainSteps"):
        rcs_mod.ReasoningChainSteps = MagicMock()  # type: ignore[attr-defined]

    # primitives.schema.edges - CITEEdgeType (real import if available, else stub)
    try:
        from primitives.schema.edges import CITEEdgeType  # noqa: F401
    except ImportError:
        import enum

        edges_mod = _ensure_stub("primitives.schema.edges")

        class _CITEEdgeType(str, enum.Enum):
            TRACED_FROM = "TRACED_FROM"

        edges_mod.CITEEdgeType = _CITEEdgeType  # type: ignore[attr-defined]

    # context_service.reactions.events - emit_reaction (ensure it exists as patchable name)
    # The real module is already importable; just ensure the name is present.
    import context_service.reactions.events as _ev_mod

    if not hasattr(_ev_mod, "emit_reaction"):
        _ev_mod.emit_reaction = AsyncMock()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Broker capture helpers
# ---------------------------------------------------------------------------

def _make_broker() -> tuple[MagicMock, dict[str, Any]]:
    from taskiq_redis import ListQueueBroker

    broker = MagicMock(spec=ListQueueBroker)
    registered_tasks: dict[str, Any] = {}

    def capture_task(task_name: str, **kwargs: Any):
        def decorator(fn: Any) -> Any:
            registered_tasks[task_name] = fn
            return fn

        return decorator

    broker.task = capture_task
    return broker, registered_tasks


def _get_handler(registered_tasks: dict[str, Any]) -> Any:
    handler = registered_tasks.get(ReactionEventType.TRACE_REASONING)
    assert handler is not None, "trace_reasoning handler not registered"
    return handler


def _make_pg_session() -> AsyncMock:
    mock_pg_session = AsyncMock()
    mock_pg_session.__aenter__ = AsyncMock(return_value=mock_pg_session)
    mock_pg_session.__aexit__ = AsyncMock(return_value=False)
    mock_pg_session.execute = AsyncMock()
    return mock_pg_session


def _build_handler(mock_ctx_svc: MagicMock, mock_pg: AsyncMock | None = None) -> Any:
    """Inject stubs and return the registered trace_reasoning handler."""
    _inject_all_stubs(mock_ctx_svc, mock_pg)

    # Re-import tasks to pick up stubs (tasks module may be cached)
    import importlib

    import context_service.reactions.tasks as tasks_mod

    importlib.reload(tasks_mod)

    broker, registered_tasks = _make_broker()
    tasks_mod.register_tasks(broker)
    return _get_handler(registered_tasks)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ctx_svc() -> MagicMock:
    ctx = MagicMock()
    ctx.graph_store = AsyncMock()
    ctx.graph_store.execute_query = AsyncMock(return_value=[])
    ctx.graph_store.execute_write = AsyncMock(return_value=[])
    ctx.graph_store.upsert_binary_edge = AsyncMock()
    return ctx


@pytest.fixture
def hypothesis_row() -> dict[str, Any]:
    return {
        "belief_id": str(uuid.uuid4()),
        "content": "The connection pool is exhausted under high load",
        "confidence": 0.75,
        "properties": {},
    }


# ---------------------------------------------------------------------------
# TX7 test classes
# ---------------------------------------------------------------------------


class TestTraceReasoningPersistsHypothesis:
    """test_trace_persists_hypothesis: a ReasoningChainSteps row is written for each uncommitted hypothesis."""

    @pytest.mark.asyncio
    async def test_trace_persists_hypothesis(
        self,
        mock_ctx_svc: MagicMock,
        hypothesis_row: dict[str, Any],
    ) -> None:
        """Handler should write one ReasoningChainSteps row per uncommitted hypothesis."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[hypothesis_row])
        mock_pg = _make_pg_session()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", new_callable=AsyncMock):
            await handler(node_id=node_id, silo_id=silo_id)

        mock_pg.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_trace_persists_multiple_hypotheses(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """One ReasoningChainSteps row should be written per uncommitted hypothesis."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        rows = [
            {"belief_id": str(uuid.uuid4()), "content": "H A", "confidence": 0.8, "properties": {}},
            {"belief_id": str(uuid.uuid4()), "content": "H B", "confidence": 0.6, "properties": {}},
        ]
        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=rows)
        mock_pg = _make_pg_session()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", new_callable=AsyncMock):
            await handler(node_id=node_id, silo_id=silo_id)

        assert mock_pg.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_trace_skips_crystallized_hypothesis(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """Hypotheses with crystallized=True should not produce a ReasoningChainSteps row."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        rows = [
            {
                "belief_id": str(uuid.uuid4()),
                "content": "Already committed",
                "confidence": 0.9,
                "properties": {"crystallized": True},
            }
        ]
        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=rows)
        mock_pg = _make_pg_session()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        await handler(node_id=node_id, silo_id=silo_id)

        mock_pg.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_creates_traced_from_edge(
        self,
        mock_ctx_svc: MagicMock,
        hypothesis_row: dict[str, Any],
    ) -> None:
        """Handler should create a TRACED_FROM edge from chain to hypothesis."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[hypothesis_row])
        mock_pg = _make_pg_session()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", new_callable=AsyncMock):
            await handler(node_id=node_id, silo_id=silo_id)

        mock_ctx_svc.graph_store.upsert_binary_edge.assert_called_once()
        edge = mock_ctx_svc.graph_store.upsert_binary_edge.call_args.args[0]
        from primitives.schema.edges import CITEEdgeType

        assert edge.type == CITEEdgeType.TRACED_FROM
        assert edge.target_id == uuid.UUID(hypothesis_row["belief_id"])


class TestTraceReasoningIdempotent:
    """test_trace_idempotent: duplicate chains are not created for already-traced sessions."""

    @pytest.mark.asyncio
    async def test_trace_noop_on_empty_hypotheses(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """No rows or edges should be written when there are no hypotheses."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[])
        mock_pg = _make_pg_session()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        await handler(node_id=node_id, silo_id=silo_id)

        mock_pg.execute.assert_not_called()
        mock_ctx_svc.graph_store.upsert_binary_edge.assert_not_called()
        mock_ctx_svc.graph_store.execute_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_insert_uses_on_conflict_do_nothing(
        self,
        mock_ctx_svc: MagicMock,
        hypothesis_row: dict[str, Any],
    ) -> None:
        """INSERT statement should use ON CONFLICT DO NOTHING to guard against duplicate chain_id."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[hypothesis_row])

        captured_stmts: list[Any] = []
        mock_pg = _make_pg_session()

        async def capture_execute(stmt: Any, *args: Any, **kwargs: Any) -> None:
            captured_stmts.append(stmt)

        mock_pg.execute = capture_execute
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", new_callable=AsyncMock):
            await handler(node_id=node_id, silo_id=silo_id)

        assert len(captured_stmts) == 1
        stmt = captured_stmts[0]
        # on_conflict_do_nothing() sets _post_values_clause on the PostgreSQL insert stmt
        assert stmt._post_values_clause is not None

    @pytest.mark.asyncio
    async def test_trace_uses_session_id_override(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """When session_id is passed it should be used instead of node_id for the graph query."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[])
        handler = _build_handler(mock_ctx_svc)

        await handler(node_id=node_id, silo_id=silo_id, session_id=session_id)

        call_kwargs = mock_ctx_svc.graph_store.execute_query.call_args.args[1]
        assert call_kwargs["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_trace_falls_back_to_node_id_when_no_session_id(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """Without session_id, node_id should be used as the effective session_id."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[])
        handler = _build_handler(mock_ctx_svc)

        await handler(node_id=node_id, silo_id=silo_id)

        call_kwargs = mock_ctx_svc.graph_store.execute_query.call_args.args[1]
        assert call_kwargs["session_id"] == node_id


class TestTraceReasoningEmitsConsensusCheck:
    """test_trace_emits_consensus_check: CHECK_CONSENSUS is emitted once per traced chain."""

    @pytest.mark.asyncio
    async def test_trace_emits_consensus_check_per_chain(
        self,
        mock_ctx_svc: MagicMock,
        hypothesis_row: dict[str, Any],
    ) -> None:
        """One CHECK_CONSENSUS event should be emitted for each traced chain."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[hypothesis_row])
        mock_pg = _make_pg_session()
        mock_emit = AsyncMock()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", mock_emit):
            await handler(node_id=node_id, silo_id=silo_id)

        mock_emit.assert_called_once()
        event = mock_emit.call_args.args[0]
        assert event.event_type == ReactionEventType.CHECK_CONSENSUS
        assert event.silo_id == silo_id

    @pytest.mark.asyncio
    async def test_trace_emits_consensus_check_for_each_chain(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """Multiple hypotheses should each produce a CHECK_CONSENSUS emit."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        rows = [
            {"belief_id": str(uuid.uuid4()), "content": "H1", "confidence": 0.8, "properties": {}},
            {"belief_id": str(uuid.uuid4()), "content": "H2", "confidence": 0.7, "properties": {}},
            {"belief_id": str(uuid.uuid4()), "content": "H3", "confidence": 0.6, "properties": {}},
        ]
        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=rows)
        mock_pg = _make_pg_session()
        mock_emit = AsyncMock()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", mock_emit):
            await handler(node_id=node_id, silo_id=silo_id)

        assert mock_emit.call_count == 3
        for c in mock_emit.call_args_list:
            event = c.args[0]
            assert event.event_type == ReactionEventType.CHECK_CONSENSUS

    @pytest.mark.asyncio
    async def test_trace_no_emit_when_no_uncommitted_hypotheses(
        self,
        mock_ctx_svc: MagicMock,
    ) -> None:
        """No CHECK_CONSENSUS event should be emitted when all hypotheses are already committed."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())

        rows = [
            {
                "belief_id": str(uuid.uuid4()),
                "content": "Already crystallized",
                "confidence": 0.9,
                "properties": {"crystallized": True},
            }
        ]
        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=rows)
        mock_emit = AsyncMock()
        handler = _build_handler(mock_ctx_svc)

        with patch("context_service.reactions.events.emit_reaction", mock_emit):
            await handler(node_id=node_id, silo_id=silo_id)

        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_trace_consensus_event_carries_session_id(
        self,
        mock_ctx_svc: MagicMock,
        hypothesis_row: dict[str, Any],
    ) -> None:
        """CHECK_CONSENSUS event payload should include the session_id."""
        silo_id = str(uuid.uuid4())
        node_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())

        mock_ctx_svc.graph_store.execute_query = AsyncMock(return_value=[hypothesis_row])
        mock_pg = _make_pg_session()
        mock_emit = AsyncMock()
        handler = _build_handler(mock_ctx_svc, mock_pg)

        with patch("context_service.reactions.events.emit_reaction", mock_emit):
            await handler(node_id=node_id, silo_id=silo_id, session_id=session_id)

        event = mock_emit.call_args.args[0]
        assert event.payload.get("session_id") == session_id
