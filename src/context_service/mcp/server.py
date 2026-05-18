# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import structlog
from fastmcp import FastMCP
from fastmcp.server.dependencies import get_http_headers

from context_service.auth.context import AuthContext

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.embeddings.splade import SpladeEncoder
    from context_service.engine.protocols import HyperGraphStore
    from context_service.mcp.preset_resolver import PresetResolver
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

    from context_service.config.settings import get_settings
    from context_service.mcp.postgres_binding_source import PostgresBindingSource
    from context_service.mcp.preset_resolver import PresetResolver

    _services["preset_resolver"] = PresetResolver(
        binding_source=PostgresBindingSource(),
        default_preset=get_settings().default_icp_preset,
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


def get_preset_resolver() -> PresetResolver:
    """Get the configured PresetResolver instance."""
    if "preset_resolver" not in _services:
        raise RuntimeError("PresetResolver not configured - call configure_services() at startup")
    from context_service.mcp.preset_resolver import PresetResolver as _PR

    return cast(_PR, _services["preset_resolver"])


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


async def _resolve_oauth_token(token: str) -> AuthContext | None:
    """Resolve auth context from our OAuth token.

    Returns AuthContext if token is valid, None otherwise.
    """
    from context_service.db.postgres import get_session
    from context_service.models.postgres.user import User
    from context_service.services.oauth import OAuthService

    async with get_session() as session:
        oauth_svc = OAuthService(session)
        oauth_token = await oauth_svc.validate_access_token(token)
        if oauth_token is None:
            return None

        user = await session.get(User, oauth_token.user_id)
        if user is None:
            return None

        return AuthContext(
            org_id=user.org_id,
            user_id=user.workos_user_id,
            email=user.email,
            is_dev=False,
            db_user_id=user.id,
        )


async def get_mcp_auth_context() -> AuthContext:
    """Resolve the MCP auth context for the current request.

    Reads the inbound Authorization header from the live FastMCP request via
    ``fastmcp.server.dependencies.get_http_headers`` and verifies it through
    either our OAuth tokens or WorkOS.  Auth is resolved per tool invocation
    (per-request), not at session start, so org boundaries are enforced on
    every call.

    Implementation note -- two auth paths exist in this package:

    1. This function (active path): reads the Authorization header on every
       tool call via FastMCP's ``get_http_headers`` dependency and returns an
       ``AuthContext``.  All tool callsites must use this function.

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
      - HTTP transport with ``Authorization: Bearer <oauth-token>``:
        verifies via our OAuth token store first and returns the resulting
        ``AuthContext`` if found.
      - HTTP transport with ``Authorization: Bearer <sealed-session>``:
        falls back to WorkOS verification and returns the resulting
        ``AuthContext``.
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

    headers = get_http_headers(include={"authorization", "x-agent-id", "x-session-id", "x-org-id"})
    auth_header = headers.get("authorization")

    if auth_header:
        token = auth_header.removeprefix("Bearer ").strip()

        # Try OAuth token first (our issued tokens).
        oauth_context = await _resolve_oauth_token(token)
        if oauth_context is not None:
            agent_id = headers.get("x-agent-id") or f"user:{oauth_context.user_id}"
            session_id: str | None = (
                headers.get("x-session-id") or hashlib.sha256(auth_header.encode()).hexdigest()
            )
            return AuthContext(
                org_id=oauth_context.org_id,
                user_id=oauth_context.user_id,
                email=oauth_context.email,
                is_dev=oauth_context.is_dev,
                agent_id=agent_id,
                session_id=session_id,
                db_user_id=oauth_context.db_user_id,
            )

        # Fall back to WorkOS sealed session (existing path).
        base = await resolve_mcp_auth_from_header(auth_header)
        agent_id = headers.get("x-agent-id") or f"user:{base.user_id}"
        # Derive a stable session identifier from the token so the same
        # sealed session always maps to the same session_id.
        session_id = headers.get("x-session-id") or hashlib.sha256(auth_header.encode()).hexdigest()
        return AuthContext(
            org_id=base.org_id,
            user_id=base.user_id,
            email=base.email,
            is_dev=base.is_dev,
            agent_id=agent_id,
            session_id=session_id,
            db_user_id=base.db_user_id,
        )

    settings = get_settings()
    if settings.auth_enabled:
        raise MCPAuthError("Missing Authorization header on authenticated MCP transport")
    # In dev mode, allow X-Org-Id header to override dev_org_id for test isolation
    org_id = headers.get("x-org-id") or settings.dev_org_id
    agent_id = headers.get("x-agent-id") or f"user:{settings.dev_user_id}"
    session_id = headers.get("x-session-id")  # str | None, already typed above
    return AuthContext(
        org_id=org_id,
        user_id=settings.dev_user_id,
        email=None,
        is_dev=True,
        agent_id=agent_id,
        session_id=session_id,
    )


async def track_tool_usage(auth: AuthContext, tool_name: str) -> None:
    """Track tool usage for authenticated users. Fire-and-forget."""
    if auth.db_user_id is None:
        return  # Dev mode or Postgres unavailable, skip tracking
    asyncio.create_task(_record_usage_task(auth.db_user_id, auth.org_id, tool_name))


async def _record_usage_task(user_id: UUID, org_id: str, tool_name: str) -> None:
    """Background task to record usage. Swallows errors."""
    try:
        from context_service.db.postgres import get_session
        from context_service.services.models import derive_silo_id
        from context_service.services.usage import UsageService

        async with get_session() as session:
            usage_service = UsageService(session)
            await usage_service.record_usage(user_id, str(derive_silo_id(org_id)), tool_name)
            await session.commit()
    except Exception as e:
        logger.warning("usage_tracking_failed", error=str(e), tool_name=tool_name)


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
        profile or os.environ.get("MCP_TOOL_PROFILE") or settings.mcp_tool_profile or "standard"
    )

    mcp = FastMCP(
        name="engrammic",
        instructions=get_mcp_instructions(),
    )

    # Register tools based on profile
    register_profile_tools(mcp, resolved_profile)

    logger.info("mcp_server_created", profile=resolved_profile)
    return mcp
