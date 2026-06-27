"""Tests for recall() tags filter parameter."""

from __future__ import annotations

import pytest

from context_service.mcp.tools.context_recall import _apply_tag_filter


def _make_node(node_id: str, tags: list[str] | None = None) -> dict:
    return {
        "node_id": node_id,
        "content": "test",
        "tags": tags or [],
    }


def test_no_filter_returns_all():
    nodes = [_make_node("a", ["foo"]), _make_node("b", ["bar"])]
    assert _apply_tag_filter(nodes, []) == nodes


def test_single_tag_match():
    nodes = [_make_node("a", ["foo", "bar"]), _make_node("b", ["bar"])]
    result = _apply_tag_filter(nodes, ["foo"])
    assert len(result) == 1
    assert result[0]["node_id"] == "a"


def test_all_tags_must_match():
    nodes = [_make_node("a", ["foo", "bar"]), _make_node("b", ["foo"])]
    result = _apply_tag_filter(nodes, ["foo", "bar"])
    assert len(result) == 1
    assert result[0]["node_id"] == "a"


def test_error_sentinel_passed_through():
    nodes = [{"error": "not_found"}, _make_node("a", ["foo"])]
    result = _apply_tag_filter(nodes, ["foo"])
    assert len(result) == 2
    assert result[0] == {"error": "not_found"}


def test_tags_in_properties():
    # ponytail: some code paths put tags in properties
    node = {"node_id": "a", "content": "test", "properties": {"tags": ["foo"]}}
    result = _apply_tag_filter([node], ["foo"])
    assert len(result) == 1
