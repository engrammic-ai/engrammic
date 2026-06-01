"""Reactions infrastructure: event-driven task processing via Taskiq."""

from context_service.reactions.broker import get_broker

__all__ = ["get_broker"]
