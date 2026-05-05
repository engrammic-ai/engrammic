"""Async Postgres session management using SQLAlchemy 2.0."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from context_service.config.settings import get_settings


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_postgres() -> AsyncEngine:
    """Initialize the Postgres connection pool."""
    global _engine, _session_factory

    settings = get_settings()
    dsn = settings.infra.postgres.dsn.get_secret_value()

    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)

    _engine = create_async_engine(
        dsn,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        _engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    return _engine


async def close_postgres() -> None:
    """Close the Postgres connection pool."""
    global _engine, _session_factory
    if _engine:
        await _engine.dispose()
        _engine = None
        _session_factory = None


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get an async session from the pool."""
    if _session_factory is None:
        await init_postgres()

    assert _session_factory is not None
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
