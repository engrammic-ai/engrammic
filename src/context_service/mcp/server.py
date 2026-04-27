# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from fastmcp import FastMCP

from context_service.auth.context import AuthContext

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService
    from context_service.stores import MemgraphClient, QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

_services: dict[str, Any] = {}
_mcp_auth_context: AuthContext | None = None


def configure_services(
    memgraph: MemgraphClient,
    qdrant: QdrantClient,
    redis: RedisClient | None = None,
    embedding: EmbeddingService | None = None,
) -> None:
    """Configure MCP service dependencies.

    Call this during application startup before serving MCP requests.
    """
    from context_service.services.context import ContextService
    from context_service.services.evidence import EvidenceValidator
    from context_service.services.silo import SiloService

    _services["context"] = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        cache=redis,
    )
    _services["silo"] = SiloService(memgraph=memgraph)
    _services["evidence"] = EvidenceValidator(memgraph=memgraph)
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


def get_mcp_auth_context() -> AuthContext:
    """Return the current MCP auth context, resolving dev bypass if needed.

    Call resolve_mcp_auth_context() during startup to populate this. When
    AUTH_ENABLED=false the unresolved fallback returns a dev AuthContext
    (safe for tests). When AUTH_ENABLED=true the unresolved state raises —
    auth must fail closed.
    """
    from context_service.auth.resolve import MCPAuthError
    from context_service.config.settings import get_settings

    if _mcp_auth_context is not None:
        return _mcp_auth_context
    settings = get_settings()
    if settings.auth_enabled:
        raise MCPAuthError(
            "MCP auth context not resolved; call resolve_mcp_auth_context() at startup"
        )
    return AuthContext(
        org_id=settings.dev_org_id,
        user_id=settings.dev_user_id,
        email=None,
        is_dev=True,
    )


async def resolve_mcp_auth_context() -> None:
    """Resolve and cache the MCP auth context at startup.

    Called once during application startup. For per-request auth, see the
    TODO in auth/resolve.py re: FastMCP transport-level header access.
    """
    global _mcp_auth_context
    from context_service.auth.resolve import resolve_mcp_auth

    _mcp_auth_context = await resolve_mcp_auth()
    logger.info("MCP auth context resolved", is_dev=_mcp_auth_context.is_dev)


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

    logger.info("MCP server created", tools=13)
    return mcp
