# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from fastmcp import FastMCP

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)

_services: dict[str, Any] = {}


def configure_services(
    # TODO: Add service dependencies as they are ported
    # store: ContextStore,
    # qdrant: QdrantStore,
    # embedding: EmbeddingService,
) -> None:
    """Configure MCP service dependencies.

    Call this during application startup before serving MCP requests.
    """
    # TODO: Wire up services when stores are ported
    # _services["context"] = ContextService(...)
    # _services["silo"] = SiloService(...)
    logger.info("MCP services configured (stub)")


def get_context_service() -> Any:
    """Get the configured ContextService instance."""
    if "context" not in _services:
        raise NotImplementedError("ContextService not yet wired - TODO: port services")
    return _services["context"]


def get_silo_service() -> Any:
    """Get the configured SiloService instance."""
    if "silo" not in _services:
        raise NotImplementedError("SiloService not yet wired - TODO: port services")
    return _services["silo"]


def create_mcp_server() -> FastMCP:
    """Create and configure the FastMCP server with all tools registered."""
    mcp = FastMCP(
        name="context-service",
        instructions="Context management service for AI agents.",
    )

    # Register core tools
    from context_service.mcp.tools.context_get import register as register_get
    from context_service.mcp.tools.context_lookup import register as register_lookup
    from context_service.mcp.tools.context_store import register as register_store
    from context_service.mcp.tools.silo import register_silo_create, register_silo_list

    register_store(mcp)
    register_get(mcp)
    register_lookup(mcp)
    register_silo_create(mcp)
    register_silo_list(mcp)

    logger.info("MCP server created", tools=5)
    return mcp
