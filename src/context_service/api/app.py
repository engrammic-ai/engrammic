"""FastAPI application factory with lifespan management."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from context_service import __version__
from context_service.api.routes import health
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

        await apply_all_indexes(memgraph_client)
        await bootstrap_custodian_schema(memgraph_client)
        logger.info("memgraph_schema_applied")

        redis_pool = await create_redis_pool(settings)
        redis_client = RedisClient(redis_pool)
        logger.info("redis_connected")

        qdrant_client = QdrantClient.from_settings(settings)
        await qdrant_client.ensure_collection()
        logger.info("qdrant_connected")

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

        configure_services(
            memgraph=memgraph_client,
            qdrant=qdrant_client,
            redis=redis_client,
            embedding=embedding_service,
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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    log_level = "DEBUG" if settings.debug else settings.log_level
    json_format = settings.environment != "development"
    configure_logging(log_level=log_level, json_format=json_format)

    docs_enabled = settings.environment != "production"

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

    app.include_router(health.router)

    return app
