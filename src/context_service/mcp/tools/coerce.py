# src/context_service/mcp/tools/coerce.py
"""Parameter coercion helpers for MCP tools.

Some MCP clients (e.g., Claude Code subagents) may send arrays as
JSON-encoded strings due to serialization quirks. These helpers
normalize both forms to ensure tools work consistently.
"""

from __future__ import annotations

import json
from typing import Any


def coerce_list(value: list[str] | str | Any) -> list[str]:
    """Coerce a value to list[str], handling JSON-encoded strings.

    Args:
        value: A list, JSON-encoded list string, or single string value.

    Returns:
        A list of strings.

    Examples:
        >>> coerce_list(["a", "b"])
        ['a', 'b']
        >>> coerce_list('["a", "b"]')
        ['a', 'b']
        >>> coerce_list("single")
        ['single']
    """
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("["):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
        return [value] if value else []
    return [str(value)]
