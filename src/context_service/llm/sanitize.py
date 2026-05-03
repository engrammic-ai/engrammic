"""Prompt sanitization utilities to prevent injection attacks."""

from __future__ import annotations


def escape_for_prompt(text: str) -> str:
    """Escape braces and wrap in data tags to prevent prompt injection.

    User-controlled content should be passed through this before interpolation
    into LLM prompts to prevent format string attacks and instruction injection.
    """
    escaped = text.replace("{", "{{").replace("}", "}}")
    return f"<data>{escaped}</data>"
