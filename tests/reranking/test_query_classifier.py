"""Tests for hard query classifier."""

from __future__ import annotations

import pytest

from context_service.reranking.query_classifier import is_hard_query


class TestIsHardQuery:
    @pytest.mark.parametrize(
        "query,expected",
        [
            # Hard queries - should return True
            ("what was rejected?", True),
            ("what got approved?", True),
            ("what failed?", True),
            ("why did the system crash?", True),
            ("what was postponed", True),
            ("which approach was abandoned?", True),
            ("is the proposal approved?", True),
            ("what was rejected!", True),
            # Normal queries - should return False
            ("meeting notes from last week", False),
            ("how to configure the database", False),
            ("list all users in the system", False),
            ("performance metrics for Q1", False),
            ("", False),
        ],
    )
    def test_is_hard_query(self, query: str, expected: bool) -> None:
        assert is_hard_query(query) == expected

    def test_case_insensitive(self) -> None:
        assert is_hard_query("WHAT WAS REJECTED?") is True
        assert is_hard_query("What Was Rejected?") is True
