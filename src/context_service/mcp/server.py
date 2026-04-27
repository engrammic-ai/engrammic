# context_service/mcp/server.py
"""FastMCP server creation and tool registration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import structlog
from fastmcp import FastMCP

if TYPE_CHECKING:
    from context_service.embeddings import EmbeddingService
    from context_service.services.context import ContextService
    from context_service.services.silo import SiloService
    from context_service.stores import MemgraphClient, QdrantClient, RedisClient

logger = structlog.get_logger(__name__)

_services: dict[str, Any] = {}


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
    from context_service.services.silo import SiloService

    _services["context"] = ContextService(
        memgraph=memgraph,
        qdrant=qdrant,
        embedding=embedding,
        cache=redis,
    )
    _services["silo"] = SiloService(memgraph=memgraph)
    logger.info("MCP services configured")


def get_context_service() -> ContextService:
    """Get the configured ContextService instance."""
    if "context" not in _services:
        raise RuntimeError("ContextService not configured — call configure_services() at startup")
    from context_service.services.context import ContextService as _CS

    return cast(_CS, _services["context"])


def get_silo_service() -> SiloService:
    """Get the configured SiloService instance."""
    if "silo" not in _services:
        raise RuntimeError("SiloService not configured — call configure_services() at startup")
    from context_service.services.silo import SiloService as _SS

    return cast(_SS, _services["silo"])


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
