# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from context_service.auth.context import AuthContext

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.embeddings.splade import SpladeEncoder
    from context_service.engine.protocols import HyperGraphStore
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService
    from context_service.stores import MemgraphClient, QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

_services: dict[str, Any] = {}


def configure_services(
    memgraph: MemgraphClient,
    qdrant: QdrantClient,
    redis: RedisClient | None = None,
    embedding: EmbeddingService | None = None,
    splade: SpladeEncoder | None = None,
) -> None:
    """Configure MCP service dependencies.

    Call this during application startup before serving MCP requests.
    """
    from context_service.cache.silo_ownership_cache import SiloOwnershipCache
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService

    _services["context"] = ContextService(
        # MemgraphClient only implements escape-hatch methods (execute_query/write, session)
        # currently; cast removable once full HyperGraphStore implementation lands.
        memgraph=cast("HyperGraphStore", memgraph),
        qdrant=qdrant,
        embedding=embedding,
        cache=redis,
        splade=splade,
    )
    ownership_cache = SiloOwnershipCache(redis) if redis is not None else None
    _services["silo"] = SiloService(memgraph=memgraph, ownership_cache=ownership_cache)
    _services["evidence"] = EvidenceValidator(store=cast("HyperGraphStore", memgraph))
    _services["redis"] = redis
    logger.info("MCP services configured")


def get_context_service() -> ContextService:
    """Get the configured ContextService instance."""
    if "context" not in _services:
        raise RuntimeError("ContextService not configured — call configure_services() at startup")
    from context_service.services.context import ContextService as _CS

    return cast(_CS, _services["context"])


def get_evidence_validator() -> EvidenceValidator:
    """Get the configured EvidenceValidator instance."""
    if "evidence" not in _services:
        raise RuntimeError(
            "EvidenceValidator not configured — call configure_services() at startup"
        )
    from context_service.services.evidence import EvidenceValidator as _EV

    return cast(_EV, _services["evidence"])


def get_silo_service() -> SiloService:
    """Get the configured SiloService instance."""
    if "silo" not in _services:
        raise RuntimeError("SiloService not configured — call configure_services() at startup")
    from context_service.services.silo import SiloService as _SS

    return cast(_SS, _services["silo"])


def get_redis() -> RedisClient | None:
    """Return the registered Redis client, or None if Redis is not wired."""
    return _services.get("redis")


async def get_mcp_auth_context() -> AuthContext:
    """Resolve the MCP auth context for the current request.

    Reads the inbound Authorization header from the live FastMCP request via
    ``fastmcp.server.dependencies.get_http_headers`` and verifies it through
    WorkOS.  Auth is resolved per tool invocation (per-request), not at
    session start, so org boundaries are enforced on every call.

    Implementation note -- two auth paths exist in this package:

    1. This function (active path): reads the Authorization header on every
       tool call via FastMCP's ``get_http_headers`` dependency and returns a
       WorkOS-backed ``AuthContext``.  All tool callsites must use this
       function.

    2. ``context_service.mcp.auth.MCPAuthMiddleware`` (not mounted --
       known limitation): a Starlette middleware that stores auth in a
       ``ContextVar`` and exposes it via ``get_mcp_auth()``.  It is not
       mounted because FastMCP does not expose a standard Starlette ``app``
       object at construction time, so there is no stable hook to attach
       Starlette middleware.  Properly wiring the middleware path is deferred
       to a future version; until then ``get_mcp_auth()`` must NOT be called
       from tool code -- the ``ContextVar`` is never populated and it will
       raise ``RuntimeError``.

    Behaviour:
      - HTTP transport with ``Authorization: Bearer <sealed-session>``:
        verifies via WorkOS and returns the resulting ``AuthContext``.
      - No header (stdio transport, dev runs, tests, or a misconfigured
        client) and ``auth_enabled=true``: raises ``MCPAuthError`` -- auth
        fails closed.
      - No header and ``auth_enabled=false``: returns a dev ``AuthContext``
        built from ``settings.dev_org_id`` / ``dev_user_id``.  The
        boot-time guard in ``Settings._validate_auth`` already prevents
        this branch in production.
    """
    from context_service.auth.resolve import (
        MCPAuthError,
        resolve_mcp_auth_from_header,
    )
    from context_service.config.settings import get_settings

    headers = get_http_headers(include={"authorization"})
    auth_header = headers.get("authorization")

    if auth_header:
        return await resolve_mcp_auth_from_header(auth_header)

    settings = get_settings()
    if settings.auth_enabled:
        raise MCPAuthError("Missing Authorization header on authenticated MCP transport")
    return AuthContext(
        org_id=settings.dev_org_id,
        user_id=settings.dev_user_id,
        email=None,
        is_dev=True,
    )


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server with all EAG tools registered."""
    mcp = FastMCP(
        name="context-service",
        instructions=(
            "EAG context management for AI agents. "
            "Use remember/assert/commit/reflect for writes, "
            "query/get/graph for reads, "
            "provenance/history for meta-memory."
        ),
    )

    # Register all EAG tools
    from context_service.mcp.tools import register_all

    register_all(mcp)

    logger.info("MCP server created", tools=14)
    return mcp
