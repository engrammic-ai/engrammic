"""Tests for signals.freshness.compute_freshness."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from context_service.signals.freshness import compute_freshness

NOW = datetime(2026, 5, 1, tzinfo=UTC)


def test_t_zero_returns_one() -> None:
    assert compute_freshness(NOW, NOW, sigma_days=30) == pytest.approx(1.0)


def test_t_equals_sigma_returns_exp_minus_half() -> None:
    created = NOW - timedelta(days=30)
    expected = math.exp(-0.5)  # ~0.6065
    assert compute_freshness(created, NOW, sigma_days=30) == pytest.approx(expected, rel=1e-6)


def test_t_three_sigma_clamped_to_floor() -> None:
    created = NOW - timedelta(days=90)
    assert compute_freshness(created, NOW, sigma_days=30) == 0.25


def test_far_future_clock_skew_clamped_to_one() -> None:
    created = NOW + timedelta(days=10)
    assert compute_freshness(created, NOW, sigma_days=30) == 1.0


def test_floor_applies_for_very_old_content() -> None:
    created = NOW - timedelta(days=10_000)
    assert compute_freshness(created, NOW, sigma_days=30) == 0.25


def test_naive_datetime_treated_as_utc() -> None:
    naive_now = datetime(2026, 5, 1)
    naive_created = datetime(2026, 5, 1)
    assert compute_freshness(naive_created, naive_now, sigma_days=30) == pytest.approx(1.0)
