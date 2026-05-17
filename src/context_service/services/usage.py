"""Tool usage tracking service."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, cast
from uuid import UUID

import structlog
from sqlalchemy import func, select

from context_service.models.postgres.usage import ToolUsage, ToolUsageSummary

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class UsageService:
    """Service for recording and aggregating MCP tool usage."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_usage(self, user_id: UUID, silo_id: str, tool_name: str) -> None:
        """Insert a ToolUsage row for a single tool invocation."""
        row = ToolUsage(user_id=user_id, silo_id=silo_id, tool_name=tool_name)
        self._session.add(row)
        await self._session.flush()
        logger.info(
            "usage.recorded",
            user_id=str(user_id),
            silo_id=silo_id,
            tool_name=tool_name,
        )

    async def get_user_usage(
        self,
        user_id: UUID,
        since: datetime | None = None,
    ) -> list[ToolUsageSummary]:
        """Aggregate usage by tool for a user.

        Returns one ToolUsageSummary per distinct tool_name, optionally
        filtered to rows where called_at >= since.
        """
        stmt = (
            select(
                ToolUsage.tool_name,
                func.count().label("count"),
                func.max(ToolUsage.called_at).label("last_used"),
            )
            .where(ToolUsage.user_id == user_id)
            .group_by(ToolUsage.tool_name)
        )
        if since is not None:
            stmt = stmt.where(ToolUsage.called_at >= since)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [
            ToolUsageSummary(tool_name=row.tool_name, count=cast(int, row.count), last_used=row.last_used)
            for row in rows
        ]

    async def get_silo_usage(
        self,
        silo_id: str,
        since: datetime | None = None,
    ) -> list[ToolUsageSummary]:
        """Aggregate usage by tool for a silo.

        Returns one ToolUsageSummary per distinct tool_name, optionally
        filtered to rows where called_at >= since.
        """
        stmt = (
            select(
                ToolUsage.tool_name,
                func.count().label("count"),
                func.max(ToolUsage.called_at).label("last_used"),
            )
            .where(ToolUsage.silo_id == silo_id)
            .group_by(ToolUsage.tool_name)
        )
        if since is not None:
            stmt = stmt.where(ToolUsage.called_at >= since)

        result = await self._session.execute(stmt)
        rows = result.all()
        return [
            ToolUsageSummary(tool_name=row.tool_name, count=cast(int, row.count), last_used=row.last_used)
            for row in rows
        ]
