"""E2E test fixtures for the 4-tool MCP surface.

Connection strategy (in priority order):
1. Real running MCP server at MCP_SERVER_URL (env var, default http://localhost:8000/mcp)
2. In-process via FastMCPTransport with configured services
3. In-process via FastMCPTransport with fake stores (no docker required)
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from context_service.auth.context import AuthContext
from context_service.services.models import Node, Silo, derive_silo_id

# ---------------------------------------------------------------------------
# Connection probe
# ---------------------------------------------------------------------------

_MCP_SERVER_URL_DEFAULT = "http://localhost:8000/mcp/"


def _get_server_url() -> str:
    import os

    return os.environ.get("MCP_SERVER_URL", _MCP_SERVER_URL_DEFAULT)


async def _probe_server(url: str) -> bool:
    """Return True if the MCP server is reachable."""
    try:
        import httpx

        health_url = url.rstrip("/").replace("/mcp", "/mcp-health")
        async with httpx.AsyncClient(timeout=1.0) as client:
            resp = await client.get(health_url)
            return resp.status_code < 500
    except Exception:
        return False


async def _probe_memgraph() -> bool:
    """Return True if Memgraph is reachable on port 7687."""
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection("localhost", 7687), timeout=1.0)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Fake store builders
# ---------------------------------------------------------------------------


def _make_fake_node(content: str = "test content") -> MagicMock:
    node = MagicMock(spec=Node)
    node.id = uuid.uuid4()
    node.content = content
    node.type = "Document"
    node.properties = {}
    return node


def _make_fake_silo(org_id: str) -> MagicMock:
    silo = MagicMock(spec=Silo)
    silo.id = derive_silo_id(org_id)
    silo.name = f"silo-{org_id}"
    silo.org_id = org_id
    silo.description = None
    silo.dissolvability = 0.5
    return silo


def _make_fake_context_service(org_id: str) -> MagicMock:
    """Build a minimal AsyncMock ContextService for in-process fake testing."""
    svc = MagicMock()
    silo_id = derive_silo_id(org_id)

    fake_node = _make_fake_node()

    async def _remember(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_fake_node(kwargs.get("content", "remembered"))

    async def _assert_claim(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_fake_node(str(kwargs.get("claim", "asserted")))

    async def _commit_belief(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_fake_node(kwargs.get("belief", "belief"))

    async def _reflect(*args: Any, **kwargs: Any) -> MagicMock:
        return _make_fake_node(kwargs.get("observation", "observation"))

    async def _reason(*args: Any, **kwargs: Any) -> MagicMock:
        result = MagicMock()
        result.chain_id = uuid.uuid4()
        return result

    async def _link(*args: Any, **kwargs: Any) -> str:
        return str(uuid.uuid4())

    async def _promote(*args: Any, **kwargs: Any) -> None:
        return None

    async def _store(*args: Any, **kwargs: Any) -> MagicMock:
        return fake_node

    async def _query(*args: Any, **kwargs: Any) -> MagicMock:
        from context_service.services.models import LookupResult, ScoredNode

        node_id = uuid.uuid4()
        return LookupResult(
            nodes=[
                ScoredNode(
                    node_id=node_id,
                    content=kwargs.get("query", "result"),
                    type="Document",
                    silo_id=silo_id,
                    score=0.95,
                )
            ],
            silos_searched=[silo_id],
            total_candidates=1,
            query=kwargs.get("query", ""),
        )

    async def _get(*args: Any, **kwargs: Any) -> MagicMock:
        from context_service.services.models import LookupResult, ScoredNode

        node_id = uuid.uuid4()
        return LookupResult(
            nodes=[
                ScoredNode(
                    node_id=node_id,
                    content="fetched content",
                    type="Document",
                    silo_id=silo_id,
                    score=1.0,
                )
            ],
            silos_searched=[silo_id],
            total_candidates=1,
            query="",
        )

    async def _graph(*args: Any, **kwargs: Any) -> MagicMock:
        from context_service.services.models import GraphResult

        return GraphResult(
            nodes=[{"node_id": str(fake_node.id), "content": fake_node.content, "layer": "memory"}],
            edges=[],
            depth_reached=0,
            nodes_visited=1,
            edges_traversed=0,
        )

    svc.remember = _remember
    svc.assert_claim = _assert_claim
    svc.commit_belief = _commit_belief
    svc.reflect = _reflect
    svc.reason = _reason
    svc.link = _link
    svc.promote_claim_to_fact = _promote
    svc.store = _store
    svc.query = _query
    svc.get = _get
    svc.graph = _graph

    # graph_store must be a fake that can answer session/execute calls for
    # reasoning chain operations.
    from tests.fakes.fake_graph_store import FakeGraphStore

    graph_store = FakeGraphStore()
    svc.graph_store = graph_store

    return svc


def _make_fake_silo_service(org_id: str) -> MagicMock:
    svc = MagicMock()
    silo = _make_fake_silo(org_id)

    async def _ensure(*args: Any, **kwargs: Any) -> MagicMock:
        return silo

    async def _get_silo(*args: Any, **kwargs: Any) -> MagicMock:
        return silo

    async def _list_silos(*args: Any, **kwargs: Any) -> list[MagicMock]:
        return [silo]

    async def _create_silo(*args: Any, **kwargs: Any) -> MagicMock:
        return silo

    svc.ensure_silo = _ensure
    svc.get_silo = _get_silo
    svc.list_silos = _list_silos
    svc.create_silo = _create_silo

    return svc


def _make_fake_evidence_validator() -> MagicMock:
    svc = MagicMock()

    async def _validate(ref: str, silo_id: str) -> MagicMock:
        result = MagicMock()
        result.status = "valid"
        result.node_id = ref.replace("node:", "")
        result.reason = None
        return result

    svc.validate = _validate
    return svc


# ---------------------------------------------------------------------------
# MCP server factory (in-process)
# ---------------------------------------------------------------------------


def _build_in_process_server(org_id: str) -> Any:
    """Create a FastMCP server with all tools registered and fake deps wired."""
    from context_service.mcp.server import (
        _services,
        create_mcp_server,
    )

    ctx_svc = _make_fake_context_service(org_id)
    silo_svc = _make_fake_silo_service(org_id)
    ev_svc = _make_fake_evidence_validator()

    _services["context"] = ctx_svc
    _services["silo"] = silo_svc
    _services["evidence"] = ev_svc
    _services["redis"] = None

    return create_mcp_server()


# ---------------------------------------------------------------------------
# Auth patch
# ---------------------------------------------------------------------------


def _make_auth(
    org_id: str, agent_id: str = "agent:e2e", session_id: str | None = None
) -> AuthContext:
    return AuthContext(
        org_id=org_id,
        user_id=f"user:{org_id}",
        email=None,
        is_dev=True,
        agent_id=agent_id,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def e2e_org_id() -> str:
    """Unique org ID per test for silo isolation."""
    return f"e2e-org-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def e2e_silo_id(e2e_org_id: str) -> str:
    return str(derive_silo_id(e2e_org_id))


@pytest.fixture
async def mcp_client(e2e_org_id: str) -> AsyncGenerator[Any, None]:
    """Provide an MCP client for e2e tests.

    Priority:
    1. Real server (if MCP_SERVER_URL is reachable)
    2. In-process FastMCPTransport with fake stores
    """
    from fastmcp import Client
    from fastmcp.client.transports import FastMCPTransport, SSETransport

    server_url = _get_server_url()
    use_real = await _probe_server(server_url)

    auth = _make_auth(e2e_org_id)

    if use_real:
        sse_transport = SSETransport(server_url.rstrip("/"))
        async with Client(sse_transport) as client:
            yield client
        return

    # In-process path: build server with fake deps + patch auth
    mcp_server = _build_in_process_server(e2e_org_id)
    in_process_transport = FastMCPTransport(mcp_server)

    with (
        patch(
            "context_service.mcp.server.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_store.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.mcp.tools.context_recall.get_mcp_auth_context",
            new=AsyncMock(return_value=auth),
        ),
        patch(
            "context_service.services.silo.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.services.silo.ensure_silo",
            new=AsyncMock(return_value=_make_fake_silo(e2e_org_id)),
        ),
    ):
        async with Client(in_process_transport) as client:
            yield client


@pytest.fixture
async def mcp_client_alt(e2e_org_id: str) -> AsyncGenerator[Any, None]:
    """Secondary MCP client for a different org, used in silo-isolation tests."""
    from fastmcp import Client
    from fastmcp.client.transports import FastMCPTransport

    alt_org_id = f"alt-{e2e_org_id}"
    alt_auth = _make_auth(alt_org_id, agent_id="agent:alt")

    mcp_server = _build_in_process_server(alt_org_id)
    transport = FastMCPTransport(mcp_server)

    with (
        patch(
            "context_service.mcp.server.get_mcp_auth_context",
            new=AsyncMock(return_value=alt_auth),
        ),
        patch(
            "context_service.mcp.tools.context_store.get_mcp_auth_context",
            new=AsyncMock(return_value=alt_auth),
        ),
        patch(
            "context_service.mcp.tools.context_link.get_mcp_auth_context",
            new=AsyncMock(return_value=alt_auth),
        ),
        patch(
            "context_service.mcp.tools.context_recall.get_mcp_auth_context",
            new=AsyncMock(return_value=alt_auth),
        ),
        patch(
            "context_service.services.silo.validate_silo_ownership",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "context_service.services.silo.ensure_silo",
            new=AsyncMock(return_value=_make_fake_silo(alt_org_id)),
        ),
    ):
        async with Client(transport) as client:
            yield client


# ---------------------------------------------------------------------------
# Helpers available to test modules
# ---------------------------------------------------------------------------


def call_result(result: Any) -> dict[str, Any]:
    """Extract the dict payload from a fastmcp CallToolResult.

    fastmcp Client.call_tool returns a CallToolResult dataclass with:
      - structured_content: dict | None  (when tool returns a dict directly)
      - data: Any                        (alias / parsed form)
      - content: list[ContentBlock]      (TextContent items carry .text as JSON string)

    This helper normalises all three shapes into a plain dict.
    """
    import json

    if isinstance(result, dict):
        return result

    # fastmcp CallToolResult dataclass
    if hasattr(result, "structured_content") and result.structured_content is not None:
        return result.structured_content  # type: ignore[return-value]

    if hasattr(result, "data") and isinstance(result.data, dict):
        return result.data  # type: ignore[return-value]

    # Fallback: parse first TextContent block
    content = getattr(result, "content", None)
    if content:
        item = content[0]
        if hasattr(item, "text"):
            text = item.text
            if isinstance(text, str):
                return json.loads(text)  # type: ignore[return-value]
            if isinstance(text, dict):
                return text  # type: ignore[return-value]

    # Last resort: list shape (older fastmcp versions)
    if isinstance(result, list) and result:
        item = result[0]
        if hasattr(item, "text"):
            return json.loads(item.text)  # type: ignore[return-value]

    raise ValueError(f"Unexpected call_tool result shape: {result!r}")
