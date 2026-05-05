"""FastAPI application factory with lifespan management."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from context_service import __version__
from context_service.api.metrics import metrics_endpoint
from context_service.api.middleware import PrometheusTimingMiddleware
from context_service.api.routes import admin, health
from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.core.service_registry import ServiceRegistry
from context_service.stores import (
    MemgraphClient,
    QdrantClient,
    RedisClient,
    create_memgraph_driver,
    create_redis_pool,
)

logger = get_logger(__name__)


class _MCPDispatcher:
    """Route /mcp/* directly to the MCP ASGI app, bypassing FastAPI middleware.

    FastAPI's ServerErrorMiddleware buffers responses to catch errors and send
    a 500 when something goes wrong. That buffering breaks SSE streaming: after
    the SSE app sends http.response.start the error middleware tries to send its
    own http.response.start on any exception, which Starlette rejects.

    By intercepting /mcp/* here — before the request ever enters FastAPI — the
    SSE transport runs outside that middleware stack entirely. The MCP app's
    lifespan is still managed by FastAPI's combined_lifespan context.
    """

    def __init__(self, fastapi_app: ASGIApp, mcp_app: ASGIApp, prefix: str = "/mcp") -> None:
        self.fastapi_app = fastapi_app
        self.mcp_app = mcp_app
        self.prefix = prefix

    def __getattr__(self, name: str) -> object:
        return getattr(self.fastapi_app, name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self.fastapi_app(scope, receive, send)
            return
        path = scope.get("path", "")
        if scope["type"] == "http" and (path == self.prefix or path.startswith(self.prefix + "/")):
            patched: dict[str, Any] = dict(scope)
            patched["path"] = path[len(self.prefix) :] or "/"
            patched["root_path"] = scope.get("root_path", "") + self.prefix
            await self.mcp_app(patched, receive, send)
            return
        await self.fastapi_app(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan."""
    settings = get_settings()

    app.state.start_time = time.monotonic()

    logger.info("creating_database_connections")

    registry = ServiceRegistry()

    try:
        memgraph_driver = await create_memgraph_driver(settings)
        memgraph_client = MemgraphClient(memgraph_driver)
        logger.info("memgraph_connected")

        from context_service.db.custodian_queries import bootstrap_custodian_schema
        from context_service.db.indexes import apply_all_indexes

        await apply_all_indexes(memgraph_client)  # type: ignore[arg-type]  # composition root passes concrete client
        await bootstrap_custodian_schema(memgraph_client)  # type: ignore[arg-type]  # composition root passes concrete client
        logger.info("memgraph_schema_applied")

        redis_pool = await create_redis_pool(settings)
        redis_client = RedisClient(redis_pool)
        logger.info("redis_connected")

        qdrant_client = QdrantClient.from_settings(settings)
        await qdrant_client.ensure_collection(hybrid=settings.hybrid_search_enabled)
        logger.info("qdrant_connected")

        from context_service.db.postgres import init_postgres

        await init_postgres()
        logger.info("postgres_connected")

        async def rebuild_memgraph() -> MemgraphClient:
            driver = await create_memgraph_driver(settings)
            return MemgraphClient(driver)

        async def rebuild_redis() -> RedisClient:
            pool = await create_redis_pool(settings)
            return RedisClient(pool)

        async def rebuild_qdrant() -> QdrantClient:
            client = QdrantClient.from_settings(settings)
            await client.ensure_collection()
            return client

        registry.register("memgraph", memgraph_client, factory=rebuild_memgraph)
        registry.register("redis", redis_client, factory=rebuild_redis)
        registry.register("qdrant", qdrant_client, factory=rebuild_qdrant)
        registry.start()

        app.state.memgraph = memgraph_client
        app.state.redis = redis_client
        app.state.qdrant = qdrant_client
        app.state.registry = registry

        from context_service.cache.embedding_cache import EmbeddingCache
        from context_service.embeddings.base import EmbeddingService
        from context_service.mcp import configure_services

        embedding_cache = EmbeddingCache(redis_client)
        embedding_service: EmbeddingService | None = None
        if settings.vertex_project_id:
            from context_service.embeddings.vertex import VertexAIEmbeddingService

            embedding_service = VertexAIEmbeddingService.from_settings(settings, embedding_cache)
        elif settings.jina_api_key:
            from context_service.embeddings.jina import JinaEmbeddingService

            embedding_service = JinaEmbeddingService.from_settings(settings, embedding_cache)

        if embedding_service is None:
            logger.warning(
                "embedding_service_unconfigured",
                hint="set jina_api_key or embedding_provider=vertex to enable semantic search",
            )
        else:
            logger.info(
                "embedding_service_configured",
                provider=type(embedding_service).__name__,
            )

        splade_encoder = None
        if settings.hybrid_search_enabled:
            from context_service.embeddings.splade import SpladeEncoder

            splade_encoder = SpladeEncoder()
            logger.info("splade_encoder_configured")

        from context_service.engine.memgraph_store import MemgraphStore
        from context_service.services.auto_tagging import AutoTaggingService

        memgraph_store = MemgraphStore(memgraph_client)

        auto_tagging: AutoTaggingService | None = None
        if embedding_service is not None:
            from context_service.db.postgres import get_session
            from context_service.services.tag_config import TagConfigService

            async with get_session() as session:
                tag_config_svc = TagConfigService(session)
                auto_tagging = AutoTaggingService(
                    embedding=embedding_service,
                    tag_config=tag_config_svc,
                )
            logger.info("auto_tagging_configured")

        configure_services(
            memgraph=memgraph_store,
            qdrant=qdrant_client,
            redis=redis_client,
            embedding=embedding_service,
            splade=splade_encoder,
            auto_tagging=auto_tagging,
        )
        logger.info("mcp_services_configured")

    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        raise

    yield

    logger.info("closing_database_connections")

    await registry.stop()

    if hasattr(app.state, "memgraph"):
        await app.state.memgraph.close()
        logger.info("memgraph_closed")

    if hasattr(app.state, "redis"):
        await app.state.redis.close()
        logger.info("redis_closed")

    if hasattr(app.state, "qdrant"):
        await app.state.qdrant.close()
        logger.info("qdrant_closed")

    from context_service.db.postgres import close_postgres

    await close_postgres()
    logger.info("postgres_closed")


def create_app() -> ASGIApp:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    log_level = "DEBUG" if settings.debug else settings.log_level
    json_format = settings.environment != "development"
    configure_logging(log_level=log_level, json_format=json_format)

    docs_enabled = settings.environment not in ("production", "staging")

    app = FastAPI(
        title="Context Service",
        description="Delta Prime context infrastructure service.",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        lifespan=lifespan,
        openapi_tags=[
            {"name": "health", "description": "Health checks and status"},
        ],
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_exception", error=str(exc), path=request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    app.add_middleware(PrometheusTimingMiddleware)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)

    if settings.mcp_enabled:
        from contextlib import asynccontextmanager

        from context_service.mcp.server import create_mcp_server

        mcp_server = create_mcp_server()
        mcp_app = mcp_server.http_app(path="/", transport="sse")

        # Store original lifespan and wrap it to include MCP lifespan
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def combined_lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
            async with original_lifespan(app_instance), mcp_app.lifespan(app_instance):
                yield

        app.router.lifespan_context = combined_lifespan

        @app.get("/mcp-health", tags=["health"])
        async def mcp_health() -> dict[str, str]:
            """Health check for MCP server."""
            return {"status": "ok", "server": mcp_server.name}

        logger.info("mcp_server_mounted", path="/mcp", transport="sse")
        return _MCPDispatcher(app, mcp_app, prefix="/mcp")

    return app
