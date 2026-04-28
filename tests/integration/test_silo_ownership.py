"""Cross-org silo-ownership regression tests.

Pins ownership enforcement at the MCP tool surface (context_query) using
a live Memgraph silo_service. ContextService is mocked because the goal
is to verify wiring of validate_silo_ownership at the tool boundary, not
the search path itself.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.services.models import derive_silo_id
from context_service.services.silo import SiloService
from context_service.stores import MemgraphClient

from .conftest import docker_available


@pytest.fixture
async def org_x_id() -> str:
    return f"test-orgx-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def org_y_id() -> str:
    return f"test-orgy-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def silo_a_id(org_x_id: str) -> uuid.UUID:
    return derive_silo_id(org_x_id)


@pytest.fixture
async def cleanup_two_silos(
    memgraph_client: MemgraphClient,
    org_x_id: str,
    org_y_id: str,
) -> AsyncIterator[None]:
    yield
    silo_a = derive_silo_id(org_x_id)
    silo_b = derive_silo_id(org_y_id)
    for sid in (silo_a, silo_b):
        await memgraph_client.execute_write(
            "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
            {"silo_id": str(sid)},
        )
        await memgraph_client.execute_write(
            "MATCH (s:Silo {id: $silo_id}) DELETE s",
            {"silo_id": str(sid)},
        )


@docker_available
@pytest.mark.integration
class TestCrossOrgSiloOwnership:
    """Org Y must not be able to read Org X's silo via MCP tools."""

    async def test_owning_org_can_read_silo(
        self,
        silo_service: SiloService,
        org_x_id: str,
        silo_a_id: uuid.UUID,
        cleanup_two_silos: None,
    ) -> None:
        """Org X creates silo A → org X reads silo A → succeeds."""
        await silo_service.get_or_create(name="Silo A", org_id=org_x_id)

        from context_service.mcp.tools import context_query as cq_mod

        auth = MagicMock()
        auth.org_id = org_x_id

        mock_ctx_svc = AsyncMock()
        mock_ctx_svc.query.return_value = []

        with (
            patch.object(cq_mod, "get_mcp_auth_context", return_value=auth),
            patch.object(cq_mod, "get_silo_service", return_value=silo_service),
            patch.object(cq_mod, "get_context_service", return_value=mock_ctx_svc),
        ):
            result = await cq_mod._context_query(
                silo_id=str(silo_a_id),
                query="anything",
            )

        assert "error" not in result
        assert "results" in result
        mock_ctx_svc.query.assert_called_once()

    async def test_foreign_org_cannot_read_silo(
        self,
        silo_service: SiloService,
        org_x_id: str,
        org_y_id: str,
        silo_a_id: uuid.UUID,
        cleanup_two_silos: None,
    ) -> None:
        """Org Y attempts to read silo A → ownership error.

        The MCP tool resolves the requesting org's expected silo from the
        auth context (org_y_id) and compares against the requested silo_id
        (silo_a_id, which is Org X's deterministic silo). The mismatch
        must surface as silo_not_found before any context-service call.
        """
        await silo_service.get_or_create(name="Silo A", org_id=org_x_id)

        from context_service.mcp.tools import context_query as cq_mod

        auth = MagicMock()
        auth.org_id = org_y_id

        mock_ctx_svc = AsyncMock()

        with (
            patch.object(cq_mod, "get_mcp_auth_context", return_value=auth),
            patch.object(cq_mod, "get_silo_service", return_value=silo_service),
            patch.object(cq_mod, "get_context_service", return_value=mock_ctx_svc),
        ):
            result = await cq_mod._context_query(
                silo_id=str(silo_a_id),
                query="anything",
            )

        assert result.get("error") == "silo_not_found"
        mock_ctx_svc.query.assert_not_called()
