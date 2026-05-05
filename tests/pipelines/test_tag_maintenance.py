"""Tests for the tag_maintenance asset.

Follows the pattern in test_auto_tagging_asset.py: tests cover the Cypher
constants and pure logic extracted from the asset body rather than calling
the decorated asset directly (which would trigger Dagster's parameter-annotation
validation at test time).
"""

from __future__ import annotations

from context_service.pipelines.assets.tag_maintenance import _ACTIVE_TAGS_CYPHER

# ---------------------------------------------------------------------------
# Cypher contract
# ---------------------------------------------------------------------------


def test_active_tags_cypher_filters_by_silo() -> None:
    assert "silo_id" in _ACTIVE_TAGS_CYPHER


def test_active_tags_cypher_uses_cutoff() -> None:
    assert "cutoff" in _ACTIVE_TAGS_CYPHER


def test_active_tags_cypher_unwinds_tags() -> None:
    assert "UNWIND n.tags" in _ACTIVE_TAGS_CYPHER


def test_active_tags_cypher_returns_distinct() -> None:
    assert "DISTINCT tag" in _ACTIVE_TAGS_CYPHER


def test_active_tags_cypher_checks_stored_or_updated() -> None:
    assert "stored_at" in _ACTIVE_TAGS_CYPHER
    assert "updated_at" in _ACTIVE_TAGS_CYPHER


# ---------------------------------------------------------------------------
# Stale-tag identification logic
# ---------------------------------------------------------------------------
#
# The stale-tag computation inside _run is:
#   stale = [t for t in dynamic_tags if t not in active_tags]
# We test this logic directly to ensure it behaves correctly across edge cases.
# ---------------------------------------------------------------------------


def _compute_stale(dynamic_tags: list[str], active_tags: list[str]) -> list[str]:
    active_set = set(active_tags)
    return [t for t in dynamic_tags if t not in active_set]


def test_stale_when_some_unused() -> None:
    stale = _compute_stale(["kept", "stale"], ["kept"])
    assert stale == ["stale"]


def test_nothing_stale_when_all_active() -> None:
    stale = _compute_stale(["a", "b"], ["a", "b", "extra"])
    assert stale == []


def test_all_stale_when_nothing_active() -> None:
    stale = _compute_stale(["x", "y"], [])
    assert stale == ["x", "y"]


def test_empty_dynamic_tags_yields_no_stale() -> None:
    stale = _compute_stale([], ["a", "b"])
    assert stale == []


def test_stale_order_preserved() -> None:
    stale = _compute_stale(["c", "a", "b"], ["a"])
    assert stale == ["c", "b"]
