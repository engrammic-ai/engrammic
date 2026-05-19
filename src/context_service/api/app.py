"""FastAPI application factory with lifespan management."""

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from context_service import __version__
from context_service.api.metrics import REGISTRY, metrics_endpoint
from context_service.api.middleware import PrometheusTimingMiddleware
from context_service.api.routes import admin, health
from context_service.api.routes.oauth import router as oauth_router
from context_service.api.routes.skills import router as skills_router
from context_service.api.routes.source_rules import router as source_rules_router
from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.core.service_registry import ServiceRegistry
from context_service.mcp.session_recovery import MCPSessionRecoveryMiddleware
from context_service.stores import (
    MemgraphClient,
    QdrantClient,
    RedisClient,
    create_memgraph_driver,
    create_redis_pool,
)
from context_service.telemetry.beacon import BeaconService
from context_service.telemetry.collector import TelemetryCollector, mark_start_time
from context_service.telemetry.install_id import get_or_create_install_id
from context_service.telemetry.tracing import instrument_fastapi, setup_tracing

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
        try:
            from context_service.config.config_loader import CONFIG_DIR, load_config
            from context_service.embeddings import build_embedding_service

            logger.info("embedding_config_loading", config_dir=str(CONFIG_DIR))
            embed_config = load_config("embeddings")
            logger.info("embedding_config_loaded", config=embed_config)
            embedding_service = build_embedding_service(embedding_cache)
            logger.info(
                "embedding_service_configured",
                provider="LiteLLMEmbeddingService",
                model=embed_config["model"],
            )
        except Exception as exc:
            logger.warning(
                "embedding_service_unconfigured",
                error_type=type(exc).__name__,
                error_message=str(exc),
                hint="create config/embeddings.yaml to enable semantic search",
            )

        splade_encoder = None
        if settings.hybrid_search_enabled:
            from context_service.embeddings.splade import SpladeEncoder

            splade_encoder = SpladeEncoder(model_name=settings.embedding.splade.model)
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

        from sqlalchemy.ext.asyncio import AsyncSession

        from context_service.db.postgres import get_engine
        from context_service.services.skills import SkillService

        skills_session = AsyncSession(get_engine(), expire_on_commit=False)
        app.state.skills_session = skills_session
        skill_service = SkillService(db=skills_session, skills_dir=Path("skills"))
        app.state.skill_service = skill_service

        configure_services(
            memgraph=memgraph_store,
            qdrant=qdrant_client,
            redis=redis_client,
            embedding=embedding_service,
            splade=splade_encoder,
            auto_tagging=auto_tagging,
            db_session=skills_session,
            skills_dir=Path("skills"),
        )
        logger.info("mcp_services_configured")

    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        raise

    # Telemetry beacon
    mark_start_time()
    beacon: BeaconService | None = None
    if settings.telemetry.enabled:
        install_id = get_or_create_install_id()
        collector = TelemetryCollector(
            install_id=install_id,
            version=__version__,
            registry=REGISTRY,
            silos=settings.telemetry.silos if settings.telemetry.tier2_enabled else None,
            all_silos=settings.telemetry.all_silos if settings.telemetry.tier2_enabled else False,
        )
        beacon = BeaconService(
            collector=collector,
            beacon_url=settings.telemetry.beacon_url,
            interval_hours=settings.telemetry.beacon_interval_hours,
        )
        await beacon.start()

    yield

    if beacon:
        await beacon.stop()
        logger.info("telemetry_beacon_stopped")

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

    if hasattr(app.state, "skills_session"):
        await app.state.skills_session.close()
        logger.info("skills_session_closed")

    from context_service.db.postgres import close_postgres

    await close_postgres()
    logger.info("postgres_closed")


def create_app() -> ASGIApp:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    log_level = "DEBUG" if settings.debug else settings.log_level
    json_format = settings.environment != "development"
    configure_logging(log_level=log_level, json_format=json_format)

    setup_tracing()

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
    instrument_fastapi(app)

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(oauth_router)
    app.include_router(skills_router)
    app.include_router(source_rules_router)
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
        return _MCPDispatcher(app, MCPSessionRecoveryMiddleware(mcp_app), prefix="/mcp")

    return app
