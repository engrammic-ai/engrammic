"""Tests for the detect_supports Dagster asset."""

import pytest

# ---------------------------------------------------------------------------
# Asset surface
# ---------------------------------------------------------------------------


def test_detect_supports_asset_exists():
    from context_service.pipelines.assets.detect_supports import detect_supports_asset

    assert detect_supports_asset is not None


def test_detect_supports_asset_name():
    from context_service.pipelines.assets.detect_supports import detect_supports_asset

    keys = list(detect_supports_asset.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "detect_supports"


def test_detect_supports_has_retry_policy():
    from context_service.pipelines.assets.detect_supports import detect_supports_asset

    policy = detect_supports_asset.op.retry_policy
    assert policy is not None
    assert policy.max_retries == 2


def test_detect_supports_in_all_assets():
    from context_service.pipelines.assets import all_assets
    from context_service.pipelines.assets.detect_supports import detect_supports_asset

    assert detect_supports_asset in all_assets


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------


def test_build_supports_prompt_includes_facts():
    from context_service.pipelines.assets.detect_supports import _build_supports_prompt

    messages = _build_supports_prompt("The API is fast.", "Latency is under 100ms.")
    assert any("The API is fast." in m["content"] for m in messages)
    assert any("Latency is under 100ms." in m["content"] for m in messages)


def test_build_supports_prompt_has_system_and_user():
    from context_service.pipelines.assets.detect_supports import _build_supports_prompt

    messages = _build_supports_prompt("A", "B")
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


def test_supports_schema_has_required_fields():
    from context_service.pipelines.assets.detect_supports import _SUPPORTS_SCHEMA

    required = set(_SUPPORTS_SCHEMA["required"])
    assert "supports" in required
    assert "confidence" in required
    assert "explanation" in required


# ---------------------------------------------------------------------------
# Confidence threshold logic
# ---------------------------------------------------------------------------


def test_supports_created_when_confidence_meets_threshold():
    from context_service.pipelines.assets.detect_supports import _SUPPORTS_CONFIDENCE_THRESHOLD

    supports = True
    confidence = 0.85
    should_create = supports and confidence >= _SUPPORTS_CONFIDENCE_THRESHOLD
    assert should_create is True


def test_false_positive_when_confidence_below_threshold():
    from context_service.pipelines.assets.detect_supports import _SUPPORTS_CONFIDENCE_THRESHOLD

    supports = True
    confidence = 0.5
    should_create = supports and confidence >= _SUPPORTS_CONFIDENCE_THRESHOLD
    assert should_create is False


def test_false_positive_when_supports_false():
    from context_service.pipelines.assets.detect_supports import _SUPPORTS_CONFIDENCE_THRESHOLD

    supports = False
    confidence = 0.95
    should_create = supports and confidence >= _SUPPORTS_CONFIDENCE_THRESHOLD
    assert should_create is False


# ---------------------------------------------------------------------------
# Cosine similarity helper
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors():
    from context_service.pipelines.assets.detect_supports import _cosine_similarity

    v = [1.0, 0.0, 0.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    from context_service.pipelines.assets.detect_supports import _cosine_similarity

    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_empty_vectors():
    from context_service.pipelines.assets.detect_supports import _cosine_similarity

    assert _cosine_similarity([], []) == 0.0


# ---------------------------------------------------------------------------
# Watermark key
# ---------------------------------------------------------------------------


def test_watermark_key_includes_silo_id():
    from context_service.pipelines.assets.detect_supports import _watermark_key

    key = _watermark_key("silo-xyz")
    assert "silo-xyz" in key
    assert "supports" in key
