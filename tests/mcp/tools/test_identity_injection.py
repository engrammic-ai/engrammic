"""Tests for identity injection and belief event logging in write tools."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from context_service.auth.context import AuthContext
from context_service.auth.identity import IdentityContext

_ORG_ID = "test-org"
_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"silo:{_ORG_ID}"))
_NODE_ID = str(uuid.uuid4())
_AGENT_ID = "agent-xyz"
_SESSION_ID = "session-abc"


def _make_identity(agent_id: str = _AGENT_ID, session_id: str = _SESSION_ID) -> IdentityContext:
    return IdentityContext(
        tenant_id=_SILO_ID,
        agent_id=agent_id,
        session_id=session_id,
        model_id=None,
    )


def _make_auth(agent_id: str | None = _AGENT_ID) -> MagicMock:
    auth = MagicMock(spec=AuthContext)
    auth.org_id = _ORG_ID
    auth.agent_id = agent_id
    auth.session_id = _SESSION_ID
    auth.db_user_id = None
    return auth


class TestFireAndForgetIdentityWrites:
    async def test_schedules_both_tasks(self) -> None:
        from context_service.services.identity_write import fire_and_forget_identity_writes

        identity = _make_identity()
        with (
            patch(
                "context_service.services.identity_write.upsert_agent",
                new=AsyncMock(),
            ),
            patch(
                "context_service.services.identity_write.log_belief_event",
                new=AsyncMock(),
            ),
            patch("context_service.services.identity_write.asyncio.create_task") as mock_task,
        ):
            fire_and_forget_identity_writes(identity, "asserted", _NODE_ID)
            assert mock_task.call_count == 2

    async def test_upsert_agent_swallows_errors(self) -> None:
        from context_service.services.identity_write import upsert_agent

        identity = _make_identity()
        with patch(
            "context_service.db.postgres.get_session",
            side_effect=RuntimeError("db_down"),
        ):
            await upsert_agent(identity)

    async def test_log_belief_event_swallows_errors(self) -> None:
        from context_service.services.identity_write import log_belief_event

        identity = _make_identity()
        with patch(
            "context_service.db.postgres.get_session",
            side_effect=RuntimeError("db_down"),
        ):
            await log_belief_event(identity, "asserted", _NODE_ID)


class TestContextRememberIdentityInjection:
    """Verify _context_remember uses identity context and fires belief event."""

    async def test_uses_identity_agent_id(self) -> None:
        identity = _make_identity(agent_id="custom-agent")

        store_result = MagicMock()
        store_result.node_id = uuid.UUID(_NODE_ID)

        with (
            patch(
                "context_service.mcp.tools.context_store.get_mcp_auth_context",
                new=AsyncMock(return_value=_make_auth()),
            ),
            patch(
                "context_service.mcp.tools.context_store.get_mcp_identity_context",
                new=AsyncMock(return_value=identity),
            ),
            patch(
                "context_service.mcp.tools.context_store.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.mcp.tools.context_store.validate_supersession_target",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.mcp.tools.context_store.store_memory",
                new=AsyncMock(return_value=(store_result, [])),
            ),
            patch(
                "context_service.mcp.tools.context_store.embed",
                new=AsyncMock(return_value=[0.1] * 4),
            ),
            patch("context_service.mcp.tools.context_store.get_context_service") as mock_svc,
            patch(
                "context_service.services.identity_write.fire_and_forget_identity_writes"
            ) as mock_ffid,
        ):
            mock_svc.return_value.vector_store.upsert = AsyncMock()
            mock_svc.return_value.graph_store = MagicMock()

            from context_service.mcp.tools.context_store import _context_remember

            result = await _context_remember(silo_id=None, content="test content")

        assert result.get("node_id") == _NODE_ID
        mock_ffid.assert_called_once_with(identity, action="asserted", target_node_id=_NODE_ID)

    async def test_fires_belief_event_on_success(self) -> None:
        identity = _make_identity()
        store_result = MagicMock()
        store_result.node_id = uuid.UUID(_NODE_ID)

        with (
            patch(
                "context_service.mcp.tools.context_store.get_mcp_auth_context",
                new=AsyncMock(return_value=_make_auth()),
            ),
            patch(
                "context_service.mcp.tools.context_store.get_mcp_identity_context",
                new=AsyncMock(return_value=identity),
            ),
            patch(
                "context_service.mcp.tools.context_store.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.mcp.tools.context_store.store_memory",
                new=AsyncMock(return_value=(store_result, [])),
            ),
            patch(
                "context_service.mcp.tools.context_store.embed",
                new=AsyncMock(return_value=[0.1] * 4),
            ),
            patch("context_service.mcp.tools.context_store.get_context_service") as mock_svc,
            patch(
                "context_service.services.identity_write.fire_and_forget_identity_writes"
            ) as mock_ffid,
        ):
            mock_svc.return_value.vector_store.upsert = AsyncMock()
            mock_svc.return_value.graph_store = MagicMock()

            from context_service.mcp.tools.context_store import _context_remember

            await _context_remember(silo_id=None, content="hello")

        mock_ffid.assert_called_once()
        _, kwargs = mock_ffid.call_args
        assert kwargs["action"] == "asserted"
