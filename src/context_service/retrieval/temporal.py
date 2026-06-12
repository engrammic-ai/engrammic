"""Temporal query parsing and recency scoring for the temporal retrieval channel.

Provides NL temporal marker parsing ("last week", "yesterday", "since monday")
and exponential decay recency scoring.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta


@dataclass
class TemporalQuery:
    """Parsed temporal constraints from a natural language query.

    Attributes:
        since: Lower bound (inclusive) for node creation time. None = no bound.
        until: Upper bound (inclusive) for node creation time. None = no bound.
        target_date: Point-in-time reference (e.g. "on tuesday"). None = no target.
        raw_markers: The original NL tokens that were matched and stripped.
    """

    since: datetime | None = None
    until: datetime | None = None
    target_date: datetime | None = None
    raw_markers: list[str] = field(default_factory=list)

    @property
    def has_constraint(self) -> bool:
        """Return True if any temporal constraint was parsed."""
        return self.since is not None or self.until is not None or self.target_date is not None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WEEKDAY_NAMES = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}


def _last_weekday(day_index: int, now: datetime) -> datetime:
    """Return the most recent past occurrence of *day_index* (0=Monday).

    If today is that weekday, returns 7 days ago (i.e. the previous week).
    """
    days_ago = (now.weekday() - day_index) % 7
    if days_ago == 0:
        days_ago = 7
    return (now - timedelta(days=days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)


def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=999999)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_temporal_query(query: str, now: datetime | None = None) -> TemporalQuery:
    """Parse natural language temporal markers from *query*.

    Recognised patterns (case-insensitive):
    - "today", "yesterday"
    - "this week", "last week", "this month", "last month"
    - "last N days/weeks/months" (e.g. "last 7 days", "last 2 weeks")
    - "in the last N days/weeks"
    - "since monday" / "since last tuesday" (day names)
    - "since yesterday", "since last week"
    - "N days ago", "N weeks ago"
    - "this year", "last year"

    Args:
        query: Raw query string from the agent.
        now: Reference time. Defaults to datetime.now(UTC).

    Returns:
        TemporalQuery with parsed constraints. If no markers found,
        all fields are None.
    """
    import re

    if now is None:
        now = datetime.now(UTC)

    result = TemporalQuery()
    q_lower = query.lower()

    # --- today ---
    if re.search(r"\btoday\b", q_lower):
        result.since = _start_of_day(now)
        result.until = now
        result.raw_markers.append("today")
        return result

    # --- yesterday ---
    if re.search(r"\byesterday\b", q_lower):
        yesterday = now - timedelta(days=1)
        result.since = _start_of_day(yesterday)
        result.until = _end_of_day(yesterday)
        result.raw_markers.append("yesterday")
        return result

    # --- last N days/weeks/months ---
    m = re.search(r"\b(?:in the )?last\s+(\d+)\s+(day|days|week|weeks|month|months)\b", q_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")  # normalise to singular
        if unit == "day":
            result.since = now - timedelta(days=n)
        elif unit == "week":
            result.since = now - timedelta(weeks=n)
        elif unit == "month":
            result.since = now - timedelta(days=n * 30)
        result.until = now
        result.raw_markers.append(m.group(0))
        return result

    # --- N days/weeks ago ---
    m = re.search(r"\b(\d+)\s+(day|days|week|weeks|month|months)\s+ago\b", q_lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if unit == "day":
            target = now - timedelta(days=n)
        elif unit == "week":
            target = now - timedelta(weeks=n)
        else:
            target = now - timedelta(days=n * 30)
        result.since = _start_of_day(target)
        result.until = _end_of_day(target)
        result.target_date = target
        result.raw_markers.append(m.group(0))
        return result

    # --- this week ---
    if re.search(r"\bthis\s+week\b", q_lower):
        start_of_week = now - timedelta(days=now.weekday())
        result.since = _start_of_day(start_of_week)
        result.until = now
        result.raw_markers.append("this week")
        return result

    # --- last week ---
    if re.search(r"\blast\s+week\b", q_lower):
        start_of_this_week = now - timedelta(days=now.weekday())
        start_of_last_week = start_of_this_week - timedelta(weeks=1)
        result.since = _start_of_day(start_of_last_week)
        result.until = _end_of_day(start_of_this_week - timedelta(seconds=1))
        result.raw_markers.append("last week")
        return result

    # --- this month ---
    if re.search(r"\bthis\s+month\b", q_lower):
        result.since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        result.until = now
        result.raw_markers.append("this month")
        return result

    # --- last month ---
    if re.search(r"\blast\s+month\b", q_lower):
        first_of_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_of_prev_month = first_of_this_month - timedelta(seconds=1)
        first_of_prev_month = last_of_prev_month.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        result.since = first_of_prev_month
        result.until = last_of_prev_month
        result.raw_markers.append("last month")
        return result

    # --- this year ---
    if re.search(r"\bthis\s+year\b", q_lower):
        result.since = now.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        result.until = now
        result.raw_markers.append("this year")
        return result

    # --- last year ---
    if re.search(r"\blast\s+year\b", q_lower):
        result.since = now.replace(
            year=now.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        result.until = now.replace(
            year=now.year - 1,
            month=12,
            day=31,
            hour=23,
            minute=59,
            second=59,
            microsecond=999999,
        )
        result.raw_markers.append("last year")
        return result

    # --- since <day_name> / since last <day_name> ---
    m = re.search(
        r"\bsince\s+(?:last\s+)?(" + "|".join(_WEEKDAY_NAMES) + r")\b", q_lower
    )
    if m:
        day_name = m.group(1)
        day_index = _WEEKDAY_NAMES[day_name]
        result.since = _last_weekday(day_index, now)
        result.until = now
        result.raw_markers.append(m.group(0))
        return result

    # --- since yesterday ---
    if re.search(r"\bsince\s+yesterday\b", q_lower):
        result.since = _start_of_day(now - timedelta(days=1))
        result.until = now
        result.raw_markers.append("since yesterday")
        return result

    # --- since last week ---
    if re.search(r"\bsince\s+last\s+week\b", q_lower):
        start_of_this_week = now - timedelta(days=now.weekday())
        result.since = _start_of_day(start_of_this_week - timedelta(weeks=1))
        result.until = now
        result.raw_markers.append("since last week")
        return result

    # --- on <day_name> (specific day reference) ---
    m = re.search(r"\bon\s+(" + "|".join(_WEEKDAY_NAMES) + r")\b", q_lower)
    if m:
        day_name = m.group(1)
        day_index = _WEEKDAY_NAMES[day_name]
        target = _last_weekday(day_index, now)
        result.since = _start_of_day(target)
        result.until = _end_of_day(target)
        result.target_date = target
        result.raw_markers.append(m.group(0))
        return result

    return result


def compute_recency_score(
    created_at: datetime,
    now: datetime,
    half_life_days: float,
) -> float:
    """Compute exponential decay recency score.

    Score is 1.0 for a brand-new node and decays toward 0 as the node ages.
    Uses the standard exponential half-life formula:

        score = 0.5 ^ (age_days / half_life_days)

    Args:
        created_at: Node creation timestamp (timezone-aware).
        now: Reference time (timezone-aware).
        half_life_days: Days after which the score halves.

    Returns:
        Float in (0.0, 1.0]. Never returns exactly 0 but approaches it.
    """
    if half_life_days <= 0:
        return 1.0

    # Ensure both datetimes are timezone-aware for subtraction
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    age_seconds = max(0.0, (now - created_at).total_seconds())
    age_days = age_seconds / 86400.0
    return math.pow(0.5, age_days / half_life_days)
