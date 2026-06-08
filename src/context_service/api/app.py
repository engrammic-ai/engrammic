"""FastAPI application factory with lifespan management."""

import os

# Disable litellm's buggy aiohttp transport BEFORE any litellm import
# Fixes instant "timeout" failures from stale session reuse
# See: https://github.com/BerriAI/litellm/issues/12425
os.environ.setdefault("DISABLE_AIOHTTP_TRANSPORT", "true")

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp

from context_service import __version__
from context_service.api.metrics import REGISTRY, metrics_endpoint
from context_service.api.middleware import PrometheusTimingMiddleware, RateLimitMiddleware
from context_service.api.routes import admin, health
from context_service.api.routes.gdpr import router as gdpr_router
from context_service.api.routes.license import router as license_router
from context_service.api.routes.oauth import router as oauth_router
from context_service.api.routes.skills import router as skills_router
from context_service.api.routes.source_rules import router as source_rules_router
from context_service.config.logging import configure_logging, get_logger
from context_service.config.settings import get_settings
from context_service.core.service_registry import ServiceRegistry
from context_service.license import check_license_on_startup
from context_service.license.version_check import check_version
from context_service.startup import verify_models
from context_service.stores import (
    MemgraphClient,
    QdrantClient,
    RedisClient,
    create_memgraph_driver,
    create_redis_pool,
)
from context_service.telemetry.beacon import BeaconService
from context_service.telemetry.collector import TelemetryCollector, mark_start_time
from context_service.telemetry.flush import flush_metrics_to_db
from context_service.telemetry.install_id import get_or_create_install_id
from context_service.telemetry.metrics import get_buffer, set_db_pool, setup_metrics

logger = get_logger(__name__)


async def _periodic_version_check(interval_hours: int = 24) -> None:
    """Background task to periodically check version."""
    from context_service.license.version_check import check_version

    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            await check_version()
        except SystemExit:
            logger.critical("unsupported_version_detected_runtime")
        except Exception as e:
            logger.warning("periodic_version_check_failed", error=str(e))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifespan."""
    settings = get_settings()

    app.state.start_time = time.monotonic()

    license_info = check_license_on_startup()
    app.state.license_info = license_info

    # Start renewal background task if license is expiring soon
    if license_info and license_info.is_expiring_soon:
        from context_service.license.renewal import attempt_license_renewal

        asyncio.create_task(attempt_license_renewal())

    # Version deprecation check (non-blocking on failure)
    if settings.telemetry.enabled:
        try:
            await check_version()
        except SystemExit:
            raise
        except Exception as e:
            logger.warning("version_check_startup_failed", error=str(e))

    logger.info("creating_database_connections")

    registry = ServiceRegistry()
    pg_pool: asyncpg.Pool | None = None
    flush_task: asyncio.Task[None] | None = None

    try:
        memgraph_driver = await create_memgraph_driver(settings)
        memgraph_client = MemgraphClient(memgraph_driver)
        logger.info("memgraph_connected")

        async def _apply_schema_background() -> None:
            """Apply indexes and schema in background to avoid blocking startup."""
            try:
                from context_service.db.custodian_queries import bootstrap_custodian_schema
                from context_service.db.indexes import apply_all_indexes

                await apply_all_indexes(memgraph_client)  # type: ignore[arg-type]
                await bootstrap_custodian_schema(memgraph_client)  # type: ignore[arg-type]
                logger.info("memgraph_schema_applied")
            except Exception as exc:
                logger.error("memgraph_schema_failed", error=str(exc))

        asyncio.create_task(_apply_schema_background())

        redis_pool = await create_redis_pool(settings)
        redis_client = RedisClient(redis_pool)
        logger.info("redis_connected")

        qdrant_client = QdrantClient.from_settings(settings)
        await qdrant_client.ensure_collection(hybrid=settings.hybrid_search_enabled)
        logger.info("qdrant_connected")

        from context_service.db.postgres import init_postgres

        await init_postgres()
        logger.info("postgres_connected")

        pg_pool = await asyncpg.create_pool(settings.postgres_dsn)

        # Initialize telemetry
        setup_metrics()
        set_db_pool(pg_pool)

        # Start background flush task
        async def periodic_flush() -> None:
            while True:
                await asyncio.sleep(60)
                buffer = get_buffer()
                if buffer is not None:
                    try:
                        await flush_metrics_to_db(pg_pool, buffer)
                    except Exception:
                        logger.exception("metrics_flush_failed")

        flush_task = asyncio.create_task(periodic_flush())

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
            # Filter sensitive keys before logging
            safe_config = {
                k: v
                for k, v in embed_config.items()
                if k.lower() not in ("api_key", "secret", "password", "token", "credential")
            }
            logger.info("embedding_config_loaded", config=safe_config)
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
            try:
                from context_service.embeddings.splade import SpladeEncoder

                splade_encoder = SpladeEncoder(model_name=settings.embedding.splade.model)
                logger.info("splade_encoder_configured")
            except ImportError:
                logger.warning(
                    "splade_unavailable", reason="torch not installed, hybrid search disabled"
                )

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

        # Start periodic version check (every 24h)
        asyncio.create_task(_periodic_version_check())

    # Verify all configured models are accessible before accepting traffic
    await verify_models()

    yield

    # Cancel flush task
    if flush_task is not None:
        flush_task.cancel()
        with suppress(asyncio.CancelledError):
            await flush_task

    # Final flush before shutdown
    if pg_pool is not None:
        buffer = get_buffer()
        if buffer is not None:
            await flush_metrics_to_db(pg_pool, buffer)
        await pg_pool.close()
        logger.info("pg_pool_closed")

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
    app.add_middleware(RateLimitMiddleware, redis=None)  # Redis injected at startup

    app.include_router(health.router)
    app.include_router(admin.router)
    app.include_router(gdpr_router)
    app.include_router(oauth_router)
    app.include_router(skills_router)
    app.include_router(source_rules_router)
    app.include_router(license_router)
    app.add_route("/metrics", metrics_endpoint, include_in_schema=False)

    if settings.mcp_enabled:
        from contextlib import asynccontextmanager

        from context_service.mcp.auth import MCPOAuthChallengeMiddleware
        from context_service.mcp.server import create_mcp_server

        mcp_server = create_mcp_server()
        # Stateless HTTP: each tool call is an independent POST request
        # No persistent connection = no cold-start initialization race on Cloud Run
        # Clients must use type: "http" in their config (not "sse")
        mcp_app = mcp_server.http_app(path="/", transport="http", stateless_http=True)

        # Add OAuth challenge middleware to return 401 with WWW-Authenticate header
        # when no token is present. This triggers OAuth flow in MCP clients (Cursor, etc.)
        # Token validation happens in the tool layer via get_mcp_auth_context()
        if settings.auth_enabled:
            mcp_app.add_middleware(MCPOAuthChallengeMiddleware)
            logger.info("mcp_oauth_challenge_middleware_enabled")

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

        app.mount("/mcp", mcp_app)
        logger.info("mcp_server_mounted", path="/mcp", transport="http")

    # Wrap app with path normalizer to prevent 307 redirects on /mcp
    # Some HTTP clients (Claude web connectors) don't follow POST redirects correctly
    class MCPPathNormalizer:
        """ASGI middleware to normalize /mcp to /mcp/ before routing."""

        def __init__(self, wrapped_app: ASGIApp) -> None:
            self.app = wrapped_app

        async def __call__(self, scope: dict[str, object], receive: object, send: object) -> None:
            if scope["type"] == "http" and scope.get("path") == "/mcp":
                scope = dict(scope)
                scope["path"] = "/mcp/"
            await self.app(scope, receive, send)  # type: ignore[arg-type]

    return MCPPathNormalizer(app)  # type: ignore[return-value]
