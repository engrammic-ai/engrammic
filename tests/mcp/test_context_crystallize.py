"""Tests for context_crystallize tool."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import context_service.mcp.tools.context_crystallize  # noqa: F401
from context_service.mcp.tools.context_crystallize import _context_crystallize
from tests.fakes.fake_graph_store import FakeGraphStore

_SILO_ID = str(uuid.uuid5(uuid.NAMESPACE_DNS, "silo:test-org"))
_BELIEF_A = str(uuid.uuid4())
_BELIEF_B = str(uuid.uuid4())


@pytest.fixture
def fake_store():
    return FakeGraphStore()


@pytest.fixture(autouse=True)
def patch_graph_store(fake_store):
    svc = AsyncMock()
    svc.graph_store = fake_store
    with patch(
        "context_service.mcp.server.get_context_service",
        return_value=svc,
    ):
        yield


class TestContextCrystallizeSuccess:
    async def test_single_belief_produces_commitment(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "ignored-by-impl"}])

        result = await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID)

        assert len(result["commitment_ids"]) == 1
        assert result["crystallized_belief_ids"] == [_BELIEF_A]
        assert "not_found" not in result

    async def test_commitment_id_is_uuid(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])

        result = await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID)

        cid = result["commitment_ids"][0]
        uuid.UUID(cid)  # raises if not a valid UUID

    async def test_multiple_beliefs_all_succeed(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])
        fake_store.seed_write_result([{"commitment_id": "y"}])

        result = await _context_crystallize(belief_ids=[_BELIEF_A, _BELIEF_B], silo_id=_SILO_ID)

        assert len(result["commitment_ids"]) == 2
        assert set(result["crystallized_belief_ids"]) == {_BELIEF_A, _BELIEF_B}
        assert "not_found" not in result

    async def test_reason_passed_to_write(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])

        await _context_crystallize(
            belief_ids=[_BELIEF_A], silo_id=_SILO_ID, reason="end of session"
        )

        assert len(fake_store.write_log) == 1
        _cypher, params = fake_store.write_log[0]
        assert params["reason"] == "end of session"
        assert params["belief_id"] == _BELIEF_A
        assert params["silo_id"] == _SILO_ID

    async def test_default_reason_when_none(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])

        await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID, reason=None)

        _cypher, params = fake_store.write_log[0]
        assert params["reason"] == "crystallized"

    async def test_write_includes_valid_from(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])

        await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID)

        _cypher, params = fake_store.write_log[0]
        assert "valid_from" in params
        assert "created_at" in params
        assert params["valid_from"] == params["created_at"]


class TestContextCrystallizePartialFailure:
    async def test_not_found_listed_when_write_returns_empty(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])
        fake_store.seed_write_result([])  # _BELIEF_B not found

        result = await _context_crystallize(belief_ids=[_BELIEF_A, _BELIEF_B], silo_id=_SILO_ID)

        assert _BELIEF_A in result["crystallized_belief_ids"]
        assert _BELIEF_B in result["not_found"]
        assert len(result["commitment_ids"]) == 1

    async def test_all_not_found(self, fake_store):
        fake_store.seed_write_result([])
        fake_store.seed_write_result([])

        result = await _context_crystallize(belief_ids=[_BELIEF_A, _BELIEF_B], silo_id=_SILO_ID)

        assert result["commitment_ids"] == []
        assert result["crystallized_belief_ids"] == []
        assert set(result["not_found"]) == {_BELIEF_A, _BELIEF_B}


class TestContextCrystallizeRationaleChain:
    async def test_rationale_chain_id_passed_to_write(self, fake_store):
        chain_id = str(uuid.uuid4())
        fake_store.seed_write_result([{"commitment_id": "x"}])

        await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID, chain_id=chain_id)

        _cypher, params = fake_store.write_log[0]
        assert params["rationale_chain_id"] == chain_id

    async def test_rationale_chain_id_none_by_default(self, fake_store):
        fake_store.seed_write_result([{"commitment_id": "x"}])

        await _context_crystallize(belief_ids=[_BELIEF_A], silo_id=_SILO_ID)

        _cypher, params = fake_store.write_log[0]
        assert params["rationale_chain_id"] is None

    async def test_commitment_links_to_reasoning_chain(self, fake_store):
        """Commitment records the rationale_chain_id that motivated it."""
        chain_id = str(uuid.uuid4())
        fake_store.seed_write_result([{"commitment_id": "x"}])

        result = await _context_crystallize(
            belief_ids=[_BELIEF_A], silo_id=_SILO_ID, chain_id=chain_id
        )

        assert len(result["commitment_ids"]) == 1
        _cypher, params = fake_store.write_log[0]
        assert params["rationale_chain_id"] == chain_id
        assert params["belief_id"] == _BELIEF_A


class TestContextCrystallizeGuards:
    async def test_empty_belief_ids_returns_error(self, fake_store):
        result = await _context_crystallize(belief_ids=[], silo_id=_SILO_ID)

        assert result["error"] == "missing_belief_ids"
        assert fake_store.write_log == []


def _capture_tool_fn() -> Any:
    """Call register() with a mock FastMCP and return the captured inner tool function."""
    from unittest.mock import MagicMock

    from context_service.mcp.tools.context_crystallize import register

    captured: dict[str, Any] = {}

    def fake_tool(**kwargs):
        def decorator(fn):
            captured["fn"] = fn
            return fn

        return decorator

    mock_mcp = MagicMock()
    mock_mcp.tool = fake_tool
    register(mock_mcp)
    assert "fn" in captured, "register() did not decorate a function"
    return captured["fn"]


class TestContextCrystallizeMCPWiring:
    """Verify that the public MCP tool wrapper passes chain_id through to the implementation."""

    async def test_chain_id_forwarded_via_mcp_wrapper(self):
        """chain_id supplied to the MCP surface must reach _context_crystallize."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from context_service.auth.context import AuthContext

        auth = AuthContext(org_id="test-org", user_id="test-user", email=None, is_dev=True)
        chain_id = str(uuid.uuid4())
        expected_result = {"commitment_ids": ["cid-1"], "crystallized_belief_ids": [_BELIEF_A]}

        tool_fn = _capture_tool_fn()

        with (
            patch(
                "context_service.mcp.server.get_mcp_auth_context",
                new=AsyncMock(return_value=auth),
            ),
            patch(
                "context_service.mcp.server.get_silo_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.services.silo.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.mcp.tools.context_crystallize._context_crystallize",
                new=AsyncMock(return_value=expected_result),
            ) as mock_impl,
        ):
            result = await tool_fn(
                belief_ids=[_BELIEF_A],
                reason="test reason",
                silo_id=_SILO_ID,
                chain_id=chain_id,
            )

        assert result == expected_result
        mock_impl.assert_awaited_once_with(
            belief_ids=[_BELIEF_A],
            silo_id=_SILO_ID,
            reason="test reason",
            chain_id=chain_id,
        )

    async def test_chain_id_none_by_default_at_mcp_surface(self):
        """Omitting chain_id at the MCP surface passes None to _context_crystallize."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from context_service.auth.context import AuthContext

        auth = AuthContext(org_id="test-org", user_id="test-user", email=None, is_dev=True)
        expected_result = {"commitment_ids": ["cid-1"], "crystallized_belief_ids": [_BELIEF_A]}

        tool_fn = _capture_tool_fn()

        with (
            patch(
                "context_service.mcp.server.get_mcp_auth_context",
                new=AsyncMock(return_value=auth),
            ),
            patch(
                "context_service.mcp.server.get_silo_service",
                return_value=MagicMock(),
            ),
            patch(
                "context_service.services.silo.validate_silo_ownership",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "context_service.mcp.tools.context_crystallize._context_crystallize",
                new=AsyncMock(return_value=expected_result),
            ) as mock_impl,
        ):
            await tool_fn(belief_ids=[_BELIEF_A], silo_id=_SILO_ID)

        _call_kwargs = mock_impl.call_args.kwargs
        assert _call_kwargs["chain_id"] is None
