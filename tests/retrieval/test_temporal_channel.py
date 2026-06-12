"""Tests for temporal query parsing and recency scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from context_service.retrieval.temporal import (
    TemporalQuery,
    compute_recency_score,
    parse_temporal_query,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Fixed reference time: Wednesday 2024-06-12 14:00 UTC
NOW = datetime(2024, 6, 12, 14, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# parse_temporal_query
# ---------------------------------------------------------------------------


class TestParseTemporalQuery:
    def test_today(self) -> None:
        result = parse_temporal_query("what did I do today?", now=NOW)
        assert result.since is not None
        assert result.since.date() == NOW.date()
        assert result.until is not None
        assert "today" in result.raw_markers

    def test_yesterday(self) -> None:
        result = parse_temporal_query("notes from yesterday", now=NOW)
        yesterday = NOW - timedelta(days=1)
        assert result.since is not None
        assert result.since.date() == yesterday.date()
        assert result.until is not None
        assert result.until.date() == yesterday.date()
        assert "yesterday" in result.raw_markers

    def test_last_n_days(self) -> None:
        result = parse_temporal_query("things I learned in the last 7 days", now=NOW)
        expected = NOW - timedelta(days=7)
        assert result.since is not None
        assert abs((result.since - expected).total_seconds()) < 2
        assert result.until is not None

    def test_last_n_weeks(self) -> None:
        result = parse_temporal_query("last 2 weeks updates", now=NOW)
        expected = NOW - timedelta(weeks=2)
        assert result.since is not None
        assert abs((result.since - expected).total_seconds()) < 2

    def test_last_week(self) -> None:
        result = parse_temporal_query("what happened last week?", now=NOW)
        assert result.since is not None
        assert result.until is not None
        # last week starts on previous Monday
        assert result.since.weekday() == 0  # Monday
        assert "last week" in result.raw_markers

    def test_this_week(self) -> None:
        result = parse_temporal_query("this week's decisions", now=NOW)
        assert result.since is not None
        assert result.since.weekday() == 0  # Monday
        assert result.until is not None

    def test_last_month(self) -> None:
        result = parse_temporal_query("bugs fixed last month", now=NOW)
        assert result.since is not None
        assert result.since.month == 5  # May (one month before June)
        assert result.since.day == 1

    def test_this_month(self) -> None:
        result = parse_temporal_query("this month's notes", now=NOW)
        assert result.since is not None
        assert result.since.month == 6
        assert result.since.day == 1

    def test_since_monday(self) -> None:
        # NOW is Wednesday; last Monday was 2024-06-10
        result = parse_temporal_query("since monday", now=NOW)
        assert result.since is not None
        assert result.since.weekday() == 0
        assert result.since.date() == datetime(2024, 6, 10, tzinfo=UTC).date()

    def test_since_last_tuesday(self) -> None:
        # NOW is Wednesday; last Tuesday was 2024-06-11
        result = parse_temporal_query("since last tuesday", now=NOW)
        assert result.since is not None
        assert result.since.weekday() == 1  # Tuesday
        assert result.until is not None

    def test_since_yesterday(self) -> None:
        result = parse_temporal_query("since yesterday morning", now=NOW)
        assert result.since is not None
        assert result.since.date() == (NOW - timedelta(days=1)).date()
        assert result.until is not None

    def test_n_days_ago(self) -> None:
        result = parse_temporal_query("3 days ago", now=NOW)
        assert result.target_date is not None
        expected_date = (NOW - timedelta(days=3)).date()
        assert result.since is not None
        assert result.since.date() == expected_date

    def test_on_weekday(self) -> None:
        # "on friday" — last Friday was 2024-06-07
        result = parse_temporal_query("what did I decide on friday?", now=NOW)
        assert result.since is not None
        assert result.since.weekday() == 4  # Friday
        assert result.target_date is not None

    def test_no_temporal_markers(self) -> None:
        result = parse_temporal_query("what is the capital of France?", now=NOW)
        assert not result.has_constraint
        assert result.since is None
        assert result.until is None
        assert result.raw_markers == []

    def test_case_insensitive(self) -> None:
        result = parse_temporal_query("LAST WEEK summary", now=NOW)
        assert result.since is not None
        assert "last week" in result.raw_markers

    def test_last_year(self) -> None:
        result = parse_temporal_query("decisions from last year", now=NOW)
        assert result.since is not None
        assert result.since.year == 2023
        assert result.until is not None
        assert result.until.year == 2023

    def test_this_year(self) -> None:
        result = parse_temporal_query("this year's progress", now=NOW)
        assert result.since is not None
        assert result.since.year == 2024
        assert result.since.month == 1
        assert result.since.day == 1

    def test_last_n_months(self) -> None:
        result = parse_temporal_query("last 3 months", now=NOW)
        expected = NOW - timedelta(days=90)
        assert result.since is not None
        assert abs((result.since - expected).total_seconds()) < 2

    def test_returns_temporal_query_type(self) -> None:
        result = parse_temporal_query("today", now=NOW)
        assert isinstance(result, TemporalQuery)

    def test_has_constraint_true(self) -> None:
        result = parse_temporal_query("last week", now=NOW)
        assert result.has_constraint

    def test_has_constraint_false(self) -> None:
        result = parse_temporal_query("no time markers", now=NOW)
        assert not result.has_constraint


# ---------------------------------------------------------------------------
# compute_recency_score
# ---------------------------------------------------------------------------


class TestComputeRecencyScore:
    def test_new_node_score_is_one(self) -> None:
        score = compute_recency_score(NOW, NOW, half_life_days=7.0)
        assert abs(score - 1.0) < 1e-9

    def test_score_at_half_life(self) -> None:
        created = NOW - timedelta(days=7)
        score = compute_recency_score(created, NOW, half_life_days=7.0)
        assert abs(score - 0.5) < 1e-6

    def test_score_at_two_half_lives(self) -> None:
        created = NOW - timedelta(days=14)
        score = compute_recency_score(created, NOW, half_life_days=7.0)
        assert abs(score - 0.25) < 1e-6

    def test_older_node_lower_score(self) -> None:
        recent = NOW - timedelta(days=1)
        old = NOW - timedelta(days=100)
        score_recent = compute_recency_score(recent, NOW, half_life_days=7.0)
        score_old = compute_recency_score(old, NOW, half_life_days=7.0)
        assert score_recent > score_old

    def test_score_always_positive(self) -> None:
        ancient = NOW - timedelta(days=3650)
        score = compute_recency_score(ancient, NOW, half_life_days=7.0)
        assert score > 0.0

    def test_score_never_exceeds_one(self) -> None:
        # Even if created_at is in the future, score should be <= 1.0
        future = NOW + timedelta(days=10)
        score = compute_recency_score(future, NOW, half_life_days=7.0)
        assert score <= 1.0

    def test_zero_half_life_returns_one(self) -> None:
        created = NOW - timedelta(days=365)
        score = compute_recency_score(created, NOW, half_life_days=0.0)
        assert score == 1.0

    def test_longer_half_life_slower_decay(self) -> None:
        created = NOW - timedelta(days=30)
        score_short = compute_recency_score(created, NOW, half_life_days=7.0)
        score_long = compute_recency_score(created, NOW, half_life_days=365.0)
        assert score_long > score_short

    def test_naive_datetime_handled(self) -> None:
        created_naive = datetime(2024, 6, 5, 0, 0, 0)  # no tzinfo
        # Should not raise
        score = compute_recency_score(created_naive, NOW, half_life_days=7.0)
        assert 0.0 < score <= 1.0

    def test_different_half_lives(self) -> None:
        """Memory (7d), Knowledge (90d), Wisdom (540d) have very different decay."""
        created = NOW - timedelta(days=30)
        memory_score = compute_recency_score(created, NOW, half_life_days=7.0)
        knowledge_score = compute_recency_score(created, NOW, half_life_days=90.0)
        wisdom_score = compute_recency_score(created, NOW, half_life_days=540.0)
        assert memory_score < knowledge_score < wisdom_score
