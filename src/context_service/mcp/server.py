# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from context_service.auth.context import AuthContext

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.embeddings.splade import SpladeEncoder
    from context_service.engine.protocols import HyperGraphStore
    from context_service.services.auto_tagging import AutoTaggingService
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService
    from context_service.services.skills import SkillService
    from context_service.stores import QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

_services: dict[str, Any] = {}


def configure_services(
    memgraph: HyperGraphStore,
    qdrant: QdrantClient,
    redis: RedisClient | None = None,
    embedding: EmbeddingService | None = None,
    splade: SpladeEncoder | None = None,
    auto_tagging: AutoTaggingService | None = None,
    db_session: Any | None = None,
    skills_dir: Path | None = None,
) -> None:
    """Configure MCP service dependencies.

    Call this during application startup before serving MCP requests.
    """
    from context_service.cache.silo_ownership_cache import SiloOwnershipCache
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService

    _services["context"] = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        cache=redis,
        splade=splade,
        auto_tagging=auto_tagging,
    )
    ownership_cache = SiloOwnershipCache(redis) if redis is not None else None
    _services["silo"] = SiloService(memgraph=memgraph, ownership_cache=ownership_cache)
    _services["evidence"] = EvidenceValidator(store=memgraph)
    _services["redis"] = redis

    if db_session is not None:
        from context_service.services.skills import SkillService

        _services["skills"] = SkillService(
            db=db_session,
            skills_dir=skills_dir or Path("skills"),
        )

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


def get_skill_service() -> SkillService:
    """Get the configured SkillService instance."""
    if "skills" not in _services:
        raise RuntimeError(
            "SkillService not configured — call configure_services() with db_session at startup"
        )
    from context_service.services.skills import SkillService as _SKS

    return cast(_SKS, _services["skills"])


def get_redis() -> RedisClient | None:
    """Return the registered Redis client, or None if Redis is not wired."""
    return _services.get("redis")


def get_postgres_store() -> Any:
    """Get or create the PostgresStore instance.

    PostgresStore is stateless (uses get_session() internally), so we lazily
    create a singleton on first access.
    """
    if "postgres_store" not in _services:
        from context_service.engine.postgres_store import PostgresStore

        _services["postgres_store"] = PostgresStore()
    return _services["postgres_store"]


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
    import hashlib

    from context_service.auth.resolve import (
        MCPAuthError,
        resolve_mcp_auth_from_header,
    )
    from context_service.config.settings import get_settings

    headers = get_http_headers(include={"authorization", "x-agent-id", "x-session-id"})
    auth_header = headers.get("authorization")

    if auth_header:
        base = await resolve_mcp_auth_from_header(auth_header)
        agent_id = headers.get("x-agent-id") or f"user:{base.user_id}"
        # Derive a stable session identifier from the token so the same
        # sealed session always maps to the same session_id.
        session_id: str | None = (
            headers.get("x-session-id") or hashlib.sha256(auth_header.encode()).hexdigest()[:32]
        )
        return AuthContext(
            org_id=base.org_id,
            user_id=base.user_id,
            email=base.email,
            is_dev=base.is_dev,
            agent_id=agent_id,
            session_id=session_id,
        )

    settings = get_settings()
    if settings.auth_enabled:
        raise MCPAuthError("Missing Authorization header on authenticated MCP transport")
    agent_id = headers.get("x-agent-id") or f"user:{settings.dev_user_id}"
    session_id = headers.get("x-session-id")  # str | None, already typed above
    return AuthContext(
        org_id=settings.dev_org_id,
        user_id=settings.dev_user_id,
        email=None,
        is_dev=True,
        agent_id=agent_id,
        session_id=session_id,
    )


def create_mcp_server(profile: str | None = None) -> FastMCP:
    """Create and configure the FastMCP server with intent-based tools.

    Args:
        profile: Tool profile override. If None, uses settings or env var.
    """
    import os

    from context_service.config.settings import get_settings
    from context_service.mcp.tools.registry import (
        get_mcp_instructions,
        register_profile_tools,
    )

    settings = get_settings()

    # Determine profile: param > env > settings > default
    resolved_profile = (
        profile
        or os.environ.get("MCP_TOOL_PROFILE")
        or settings.mcp_tool_profile
        or "standard"
    )

    mcp = FastMCP(
        name="engrammic",
        instructions=get_mcp_instructions(),
    )

    # Register tools based on profile
    register_profile_tools(mcp, resolved_profile)

    logger.info("mcp_server_created", profile=resolved_profile)
    return mcp
