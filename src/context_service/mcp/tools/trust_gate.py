"""Recall trust gate (A1): withhold memory the system cannot stand behind."""

from __future__ import annotations

from typing import Any


def apply_trust_gate(
    results: list[dict[str, Any]],
    *,
    confidence_floor: float,
    withhold_conflicts: bool,
    include_withheld: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Partition recall results into surfaced vs withheld.

    Withholds items with conflict_status == "unresolved" (if withhold_conflicts)
    or confidence below confidence_floor. Missing confidence is treated as 1.0
    (do not penalize absent data); missing conflict_status as "none".

    Returns (surfaced_results, withheld_summary). withheld_summary is
    {"count": int, "by_reason": {"unresolved_conflict": int, "low_confidence": int}}.
    """
    by_reason: dict[str, int] = {"unresolved_conflict": 0, "low_confidence": 0}
    if include_withheld:
        return list(results), {"count": 0, "by_reason": by_reason}

    surfaced: list[dict[str, Any]] = []
    count = 0
    for item in results:
        status = item.get("conflict_status") or "none"
        raw_conf = item.get("confidence")
        confidence = 1.0 if raw_conf is None else float(raw_conf)

        reason: str | None = None
        if withhold_conflicts and status == "unresolved":
            reason = "unresolved_conflict"
        elif confidence < confidence_floor:
            reason = "low_confidence"

        if reason is None:
            surfaced.append(item)
        else:
            count += 1
            by_reason[reason] += 1

    summary: dict[str, Any] = {"count": count, "by_reason": by_reason}
    return surfaced, summary
