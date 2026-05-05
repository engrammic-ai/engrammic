# tests/pipelines/test_auto_tagging_asset.py
import json

from context_service.pipelines.assets.auto_tagging import (
    _BATCH_SIZE,
    _FETCH_UNTAGGED_CYPHER,
    _UPDATE_NODE_TAGS_CYPHER,
    _build_prompt,
    _parse_tag_response,
)


def test_batch_size():
    assert _BATCH_SIZE == 50


def test_fetch_cypher_filters_untagged():
    assert "auto_tagged_at IS NULL" in _FETCH_UNTAGGED_CYPHER
    assert "silo_id" in _FETCH_UNTAGGED_CYPHER
    assert "LIMIT" in _FETCH_UNTAGGED_CYPHER


def test_update_cypher_sets_tags_and_timestamp():
    assert "n.tags = $tags" in _UPDATE_NODE_TAGS_CYPHER
    assert "n.auto_tagged_at = $auto_tagged_at" in _UPDATE_NODE_TAGS_CYPHER


def test_build_prompt_includes_node_ids():
    nodes = [
        {"node_id": "abc123", "content": "Some content here", "labels": ["Memory"]},
        {"node_id": "def456", "content": "Other content", "labels": ["Knowledge"]},
    ]
    prompt = _build_prompt(nodes)
    assert "abc123" in prompt
    assert "def456" in prompt
    assert "Some content here" in prompt


def test_build_prompt_truncates_content():
    long_content = "x" * 1000
    nodes = [{"node_id": "n1", "content": long_content, "labels": []}]
    prompt = _build_prompt(nodes)
    # Content should be capped at 400 chars per node.
    assert "x" * 401 not in prompt


def test_build_prompt_handles_missing_content():
    nodes = [{"node_id": "n2", "content": None, "labels": ["Memory"]}]
    prompt = _build_prompt(nodes)
    assert "n2" in prompt


def test_parse_tag_response_valid():
    raw = json.dumps({"node1": ["alpha", "beta"], "node2": ["gamma"]})
    result = _parse_tag_response(raw)
    assert result == {"node1": ["alpha", "beta"], "node2": ["gamma"]}


def test_parse_tag_response_strips_markdown_fences():
    raw = '```json\n{"n1": ["a", "b"]}\n```'
    result = _parse_tag_response(raw)
    assert result == {"n1": ["a", "b"]}


def test_parse_tag_response_invalid_json_returns_empty():
    result = _parse_tag_response("not json at all")
    assert result == {}


def test_parse_tag_response_non_dict_returns_empty():
    result = _parse_tag_response(json.dumps([1, 2, 3]))
    assert result == {}


def test_parse_tag_response_skips_non_list_values():
    raw = json.dumps({"n1": ["good"], "n2": "bad_string"})
    result = _parse_tag_response(raw)
    assert "n1" in result
    assert "n2" not in result
