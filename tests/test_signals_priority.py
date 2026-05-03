"""Tests for signals.priority.compute_consensus_priority."""

from __future__ import annotations

import math

import pytest

from context_service.signals.priority import compute_consensus_priority


def test_zero_heat_yields_zero_priority() -> None:
    assert compute_consensus_priority(0.5, 0.0, 3) == 0.0


def test_full_confidence_yields_zero_priority() -> None:
    assert compute_consensus_priority(1.0, 0.8, 3) == 0.0


def test_single_agent_low_priority() -> None:
    """Agent count = 1 yields log(2) factor — low compared to multi-agent."""
    single = compute_consensus_priority(0.2, 0.8, 1)
    multi = compute_consensus_priority(0.2, 0.8, 3)
    assert single < multi
    assert single == pytest.approx((1 - 0.2) * 0.8 * math.log(2))


def test_agent_count_caps_at_five() -> None:
    five = compute_consensus_priority(0.3, 0.7, 5)
    ten = compute_consensus_priority(0.3, 0.7, 10)
    assert five == pytest.approx(ten)


def test_confidence_clamped_to_unit_interval() -> None:
    assert compute_consensus_priority(-0.5, 0.5, 3) == compute_consensus_priority(0.0, 0.5, 3)
    assert compute_consensus_priority(2.0, 0.5, 3) == compute_consensus_priority(1.0, 0.5, 3)
