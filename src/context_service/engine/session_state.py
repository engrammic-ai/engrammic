"""Redis-backed session state for tick() engagement tracking."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from redis.asyncio import Redis

SESSION_TTL_SECONDS = 4 * 60 * 60  # 4 hours
DEBOUNCE_TICKS = 3
MAX_IGNORES_BEFORE_SUPPRESS = 3


class SessionState(BaseModel):
    """Session state for tick() engagement tracking."""

    session_id: str
    turn_count: int = 0
    last_store_turn: int = 0
    shown_nudges: dict[str, list[int]] = Field(default_factory=dict)
    ignored_nudges: dict[str, int] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def should_show_nudge(self, nudge_type: str) -> bool:
        """Check if nudge should be shown based on debouncing rules."""
        if self.ignored_nudges.get(nudge_type, 0) >= MAX_IGNORES_BEFORE_SUPPRESS:
            return False
        shown_turns = self.shown_nudges.get(nudge_type, [])
        if shown_turns:
            last_shown = max(shown_turns)
            if self.turn_count - last_shown < DEBOUNCE_TICKS:
                return False
        return True

    def record_nudge_shown(self, nudge_type: str) -> None:
        """Record that a nudge was shown this turn."""
        if nudge_type not in self.shown_nudges:
            self.shown_nudges[nudge_type] = []
        self.shown_nudges[nudge_type].append(self.turn_count)
        self.shown_nudges[nudge_type] = self.shown_nudges[nudge_type][-10:]

    def record_nudge_ignored(self, nudge_type: str) -> None:
        """Record that a nudge was ignored."""
        self.ignored_nudges[nudge_type] = self.ignored_nudges.get(nudge_type, 0) + 1


def _session_key(silo_id: str, session_id: str) -> str:
    return f"session:{silo_id}:{session_id}"


async def get_or_create_session(
    redis: Redis,
    session_id: str | None,
    silo_id: str,
) -> SessionState:
    """Get existing session or create new one."""
    if session_id:
        data = await redis.get(_session_key(silo_id, session_id))
        if data:
            return SessionState.model_validate_json(data)

    new_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
    session = SessionState(session_id=new_id)
    await redis.setex(
        _session_key(silo_id, new_id),
        SESSION_TTL_SECONDS,
        session.model_dump_json(),
    )
    return session


async def save_session(redis: Redis, session: SessionState, silo_id: str) -> None:
    """Save session state to Redis."""
    await redis.setex(
        _session_key(silo_id, session.session_id),
        SESSION_TTL_SECONDS,
        session.model_dump_json(),
    )


async def increment_turn(redis: Redis, session: SessionState, silo_id: str) -> SessionState:
    """Increment turn count and save."""
    session.turn_count += 1
    await save_session(redis, session, silo_id)
    return session
