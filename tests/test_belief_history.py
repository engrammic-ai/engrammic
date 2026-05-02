"""Unit tests for belief history engine."""
from __future__ import annotations

from datetime import datetime

from context_service.engine.history import build_belief_timeline, compute_confidence_trend

# ---------------------------------------------------------------------------
# compute_confidence_trend
# ---------------------------------------------------------------------------

def test_trend_increasing() -> None:
    assert compute_confidence_trend([0.5, 0.7, 0.9]) == "increasing"


def test_trend_decreasing() -> None:
    assert compute_confidence_trend([0.9, 0.7, 0.5]) == "decreasing"


def test_trend_stable() -> None:
    assert compute_confidence_trend([0.8, 0.8, 0.8]) == "stable"


def test_trend_volatile() -> None:
    # large swing, non-monotonic
    assert compute_confidence_trend([0.9, 0.3, 0.95]) == "volatile"


def test_trend_single_item() -> None:
    assert compute_confidence_trend([0.7]) == "stable"


def test_trend_empty() -> None:
    assert compute_confidence_trend([]) == "stable"


# ---------------------------------------------------------------------------
# build_belief_timeline
# ---------------------------------------------------------------------------

def _make_rows(
    *entries: tuple[str, float, str | None, str | None, str | None],
) -> list[dict]:
    """Build fake Memgraph row dicts. Each entry: (id, confidence, valid_from_iso, valid_to_iso, superseded_by)."""
    rows = []
    for node_id, conf, vf, vt, sup_by in entries:
        rows.append({
            "id": node_id,
            "content": f"content of {node_id}",
            "confidence": conf,
            "valid_from": datetime.fromisoformat(vf) if vf else None,
            "valid_to": datetime.fromisoformat(vt) if vt else None,
            "superseded_by": sup_by,
        })
    return rows


def test_single_fact_no_history() -> None:
    rows = _make_rows(("fact-a", 0.8, "2026-01-01T00:00:00+00:00", None, None))
    history = build_belief_timeline("fact-a", rows)
    assert len(history.timeline) == 1
    assert history.timeline[0].status == "current"
    assert history.total_versions == 1


def test_linear_supersession_chain() -> None:
    rows = _make_rows(
        ("fact-a", 0.7, "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "fact-b"),
        ("fact-b", 0.9, "2026-02-01T00:00:00+00:00", None, None),
    )
    history = build_belief_timeline("fact-a", rows)
    assert len(history.timeline) == 2
    assert history.timeline[0].status == "superseded"
    assert history.timeline[1].status == "current"
    assert history.confidence_trend == "increasing"


def test_cycle_guard() -> None:
    """Rows with a cycle (a->b->a) must not cause infinite loop."""
    rows = _make_rows(
        ("fact-a", 0.7, "2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", "fact-b"),
        ("fact-b", 0.8, "2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00", "fact-a"),
    )
    history = build_belief_timeline("fact-a", rows)
    # Should complete without hanging; both facts in timeline
    assert len(history.timeline) == 2
