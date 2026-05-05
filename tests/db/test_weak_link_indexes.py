"""Tests for WeakLink node index DDL in db/indexes.py."""

from __future__ import annotations

from context_service.db.indexes import ALL_INDEX_QUERIES, WEAK_LINK_INDEX_QUERIES


def test_weak_link_index_queries_exist() -> None:
    assert len(WEAK_LINK_INDEX_QUERIES) == 3
    assert "CREATE INDEX ON :WeakLink(id);" in WEAK_LINK_INDEX_QUERIES
    assert "CREATE INDEX ON :WeakLink(silo_id);" in WEAK_LINK_INDEX_QUERIES
    assert "CREATE INDEX ON :WeakLink(speculative);" in WEAK_LINK_INDEX_QUERIES


def test_weak_link_indexes_in_all_index_queries() -> None:
    for q in WEAK_LINK_INDEX_QUERIES:
        assert q in ALL_INDEX_QUERIES, f"Missing from ALL_INDEX_QUERIES: {q}"
