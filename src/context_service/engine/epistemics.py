"""Canonical interpretation of epistemic node properties.

Single source of truth for what ABSENT epistemic state means on read
paths. Convention (matching mcp/tools/trust_gate.py): missing confidence
means "never assessed" and is never penalized, never boosted. A present
confidence - INCLUDING 0.0 - is respected as-is.

Why this module exists: read sites used `props.get("confidence") or 1.0`,
whose falsy `or` maps a stored 0.0 (assessed, zero confidence) to 1.0
(full trust). See context/review/2026-06-11-architecture-epistemics-critique.md
finding E2.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def read_confidence(props: Mapping[str, Any]) -> float | None:
    """Return the node's confidence clamped to [0, 1], or None when never assessed.

    Never use ``props.get("confidence") or default``: the falsy ``or``
    maps a stored 0.0 to the default.
    """
    raw = props.get("confidence")
    if raw is None:
        return None
    return max(0.0, min(1.0, float(raw)))


def effective_confidence(props: Mapping[str, Any], *, when_missing: float = 1.0) -> float:
    """Confidence for contexts that need a scalar. Missing -> ``when_missing``.

    ``when_missing=1.0`` is the trust-gate convention (do not penalize
    absent data). Callers must not pass ``when_missing=0.0`` on read
    paths: treating unassessed as worthless is a ranking decision, not
    a data default.
    """
    conf = read_confidence(props)
    return when_missing if conf is None else conf
