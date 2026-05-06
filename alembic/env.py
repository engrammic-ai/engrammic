"""Alembic env.py — async Postgres migrations."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from alembic import context

# Import Base so SQLAlchemy metadata is populated.
from context_service.db.postgres import Base  # noqa: F401

# Import models to register them against Base.metadata before autogenerate runs.
from context_service.models.tag_config import SiloTagConfig  # noqa: F401
from context_service.models.postgres import (  # noqa: F401
    AuditEvents,
    Events,
    OrgPreferences,
    OrphanedChains,
    ReasoningChainSteps,
    SiloConfig,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_dsn() -> str:
    """Resolve the Postgres DSN at runtime.

    Precedence:
    1. POSTGRES_DSN environment variable (plain string, not SecretStr)
    2. settings.infra.postgres.dsn (pydantic SecretStr)

    The DSN is rewritten to use the asyncpg driver if needed.
    """
    dsn = os.environ.get("POSTGRES_DSN") or os.environ.get("INFRA__POSTGRES__DSN")
    if not dsn:
        # Fall back to settings (loads .env / YAML if present).
        from context_service.config.settings import get_settings

        dsn = get_settings().infra.postgres.dsn

    # Ensure asyncpg driver.
    if dsn.startswith("postgresql://"):
        dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif dsn.startswith("postgres://"):
        dsn = dsn.replace("postgres://", "postgresql+asyncpg://", 1)

    return dsn


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (no live connection required).

    Useful for generating SQL scripts to review before applying.
    """
    url = _get_dsn()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    cfg_section = config.get_section(config.config_ini_section, {})
    cfg_section["sqlalchemy.url"] = _get_dsn()

    connectable = async_engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
