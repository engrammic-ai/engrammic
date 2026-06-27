"""Integration test fixtures for live docker stack."""

from __future__ import annotations

import os
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


def _check_service_available(host: str = "127.0.0.1", port: int = 8000) -> bool:
    """Check if the REST service is reachable."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((host, port))
        s.close()
        return True
    except (TimeoutError, OSError):
        return False


docker_available = pytest.mark.skipif(
    not _check_docker_available(),
    reason="Docker stack not running (Memgraph on 7687)",
)

service_available = pytest.mark.skipif(
    not _check_service_available(
        host=os.environ.get("INTEGRATION_HOST", "127.0.0.1"),
        port=int(os.environ.get("INTEGRATION_PORT", "8000")),
    ),
    reason="Service not running (default: 127.0.0.1:8000)",
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
async def integration_client() -> AsyncIterator[object]:
    """AsyncClient pointed at a live running service instance.

    Skipped automatically when the service is not reachable.
    Set INTEGRATION_HOST / INTEGRATION_PORT env vars to override defaults.
    """
    import httpx

    host = os.environ.get("INTEGRATION_HOST", "127.0.0.1")
    port = int(os.environ.get("INTEGRATION_PORT", "8000"))

    if not _check_service_available(host, port):
        pytest.skip(f"Service not running at {host}:{port}")

    base_url = f"http://{host}:{port}"
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        yield client


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
