"""Error response helpers for MCP tools.

All MCP tool error responses share a consistent envelope:

    {
        "success": False,
        "error": {
            "code": "<UPPER_SNAKE_CODE>",
            "message": "<human readable>",
            "details": {...}   # optional
        },
        "ignored_flags": ["flag1"]  # optional, flags passed but not applicable
    }

Success responses carry ``"success": True`` and an optional
``"ignored_flags"`` list when the caller passed parameters that are silently
not applicable to the chosen operation mode.
"""

from __future__ import annotations

from typing import Any


def error_response(
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    ignored_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Return a standardised MCP error envelope.

    Parameters
    ----------
    code:
        Upper-snake-case error code, e.g. ``"VALIDATION_ERROR"``.
    message:
        Human-readable description of the error.
    details:
        Optional additional context (valid values, offending fields, etc.).
    ignored_flags:
        Parameter names that were supplied by the caller but are not
        applicable to the current operation.
    """
    result: dict[str, Any] = {
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if details:
        result["error"]["details"] = details
    if ignored_flags:
        result["ignored_flags"] = ignored_flags
    return result


def success_response(
    data: dict[str, Any],
    ignored_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Wrap a successful result dict with the standard envelope fields.

    Parameters
    ----------
    data:
        The tool-specific result payload.
    ignored_flags:
        Parameter names that were supplied by the caller but are not
        applicable to the current operation.
    """
    result: dict[str, Any] = {"success": True, **data}
    if ignored_flags:
        result["ignored_flags"] = ignored_flags
    return result
