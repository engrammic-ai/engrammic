"""Reactions infrastructure: event-driven task processing via Taskiq."""

from context_service.reactions.broker import get_broker
from context_service.reactions.events import ReactionEvent, ReactionEventType, emit_reaction
from context_service.reactions.tasks import register_tasks
from context_service.reactions.worker import configure_worker

__all__ = [
    "ReactionEvent",
    "ReactionEventType",
    "configure_worker",
    "emit_reaction",
    "get_broker",
    "register_tasks",
]
