"""Integration test fixtures for live docker stack."""

from __future__ import annotations

import socket
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import pytest

from context_service.config.settings import get_settings
from context_service.services.models import ScopeContext, derive_silo_id
from context_service.services.silo import SiloService
from context_service.stores import MemgraphClient, create_memgraph_driver

if TYPE_CHECKING:
    from neo4j import AsyncDriver


def _check_docker_available() -> bool:
    """Check if docker stack is running."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("localhost", 7687))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


docker_available = pytest.mark.skipif(
    not _check_docker_available(),
    reason="Docker stack not running (Memgraph on 7687)",
)


@pytest.fixture
def unique_org_id() -> str:
    """Generate unique org_id per test to avoid collisions."""
    return f"test-org-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def unique_silo_id(unique_org_id: str) -> uuid.UUID:
    """Derive silo_id from unique org_id."""
    return derive_silo_id(unique_org_id)


@pytest.fixture
async def memgraph_driver() -> AsyncIterator[AsyncDriver]:
    """Create Memgraph driver, close after test."""
    settings = get_settings()
    driver = await create_memgraph_driver(settings)
    yield driver
    await driver.close()


@pytest.fixture
async def memgraph_client(memgraph_driver: AsyncDriver) -> MemgraphClient:
    """Memgraph client wrapper."""
    return MemgraphClient(memgraph_driver)


@pytest.fixture
async def silo_service(memgraph_client: MemgraphClient) -> SiloService:
    """SiloService instance."""
    return SiloService(memgraph_client)


@pytest.fixture
def scope_context(
    unique_org_id: str,
    unique_silo_id: uuid.UUID,
) -> ScopeContext:
    """ScopeContext for test isolation."""
    return ScopeContext(org_id=unique_org_id, silo_id=unique_silo_id)


@pytest.fixture
async def cleanup_silo(
    memgraph_client: MemgraphClient,
    unique_silo_id: uuid.UUID,
) -> AsyncIterator[None]:
    """Cleanup test silo and nodes after test."""
    yield
    await memgraph_client.execute_write(
        "MATCH (n {silo_id: $silo_id}) DETACH DELETE n",
        {"silo_id": str(unique_silo_id)},
    )
    await memgraph_client.execute_write(
        "MATCH (s:Silo {id: $silo_id}) DELETE s",
        {"silo_id": str(unique_silo_id)},
    )
