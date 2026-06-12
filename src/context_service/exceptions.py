"""Shared exceptions for context_service.

This module contains exceptions used across api and mcp layers to avoid
circular imports.
"""

from __future__ import annotations


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, retry_after: int, limit: int, current: int, category: str) -> None:
        self.retry_after = retry_after
        self.limit = limit
        self.current = current
        self.category = category
        super().__init__(f"Rate limit exceeded for {category}: {current}/{limit}")
