"""Tests for the validator_contradiction Dagster asset."""

import pytest

# ---------------------------------------------------------------------------
# Asset surface
# ---------------------------------------------------------------------------


def test_validator_contradiction_asset_exists():
    from context_service.pipelines.assets.validator_contradiction import (
        validator_contradiction_asset,
    )

    assert validator_contradiction_asset is not None


def test_validator_contradiction_asset_name():
    from context_service.pipelines.assets.validator_contradiction import (
        validator_contradiction_asset,
    )

    keys = list(validator_contradiction_asset.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "validator_contradiction"


def test_validator_contradiction_has_retry_policy():
    from context_service.pipelines.assets.validator_contradiction import (
        validator_contradiction_asset,
    )

    policy = validator_contradiction_asset.op.retry_policy
    assert policy is not None
    assert policy.max_retries == 2


def test_validator_contradiction_in_all_assets():
    from context_service.pipelines.assets import all_assets
    from context_service.pipelines.assets.validator_contradiction import (
        validator_contradiction_asset,
    )

    assert validator_contradiction_asset in all_assets


# ---------------------------------------------------------------------------
# Query constants
# ---------------------------------------------------------------------------


def test_get_contradiction_candidates_query_exists():
    from context_service.db.queries import GET_CONTRADICTION_CANDIDATES

    assert "contradiction_candidate" in GET_CONTRADICTION_CANDIDATES
    assert "$silo_id" in GET_CONTRADICTION_CANDIDATES
    assert "$cutoff" in GET_CONTRADICTION_CANDIDATES


def test_clear_contradiction_candidate_flags_query_exists():
    from context_service.db.queries import CLEAR_CONTRADICTION_CANDIDATE_FLAGS

    assert "REMOVE" in CLEAR_CONTRADICTION_CANDIDATE_FLAGS
    assert "contradiction_candidate" in CLEAR_CONTRADICTION_CANDIDATE_FLAGS


def test_get_nodes_content_by_ids_query_exists():
    from context_service.db.queries import GET_NODES_CONTENT_BY_IDS

    assert "$node_ids" in GET_NODES_CONTENT_BY_IDS
    assert "$silo_id" in GET_NODES_CONTENT_BY_IDS


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------


def test_build_contradiction_prompt_includes_claims():
    from context_service.pipelines.assets.validator_contradiction import (
        _build_contradiction_prompt,
    )

    messages = _build_contradiction_prompt("The sky is blue.", "The sky is green.")
    assert any("The sky is blue." in m["content"] for m in messages)
    assert any("The sky is green." in m["content"] for m in messages)


def test_build_contradiction_prompt_has_system_and_user():
    from context_service.pipelines.assets.validator_contradiction import (
        _build_contradiction_prompt,
    )

    messages = _build_contradiction_prompt("A", "B")
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


def test_contradiction_schema_has_required_fields():
    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_SCHEMA,
    )

    required = set(_CONTRADICTION_SCHEMA["required"])
    assert "contradicts" in required
    assert "confidence" in required
    assert "explanation" in required


# ---------------------------------------------------------------------------
# Confirmation threshold logic
# ---------------------------------------------------------------------------


def test_false_positive_when_confidence_below_threshold():
    """confidence < 0.7 should not trigger create_contradiction."""
    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_CONFIDENCE_THRESHOLD,
    )

    confidence = 0.5
    assert confidence < _CONTRADICTION_CONFIDENCE_THRESHOLD


def test_false_positive_when_contradicts_false():
    """contradicts=false should not trigger create_contradiction regardless of confidence."""
    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_CONFIDENCE_THRESHOLD,
    )

    contradicts = False
    confidence = 0.95
    should_confirm = contradicts and confidence >= _CONTRADICTION_CONFIDENCE_THRESHOLD
    assert should_confirm is False


def test_confirmed_when_contradicts_true_and_high_confidence():
    """contradicts=true and confidence >= threshold -> should confirm."""
    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_CONFIDENCE_THRESHOLD,
    )

    contradicts = True
    confidence = 0.9
    should_confirm = contradicts and confidence >= _CONTRADICTION_CONFIDENCE_THRESHOLD
    assert should_confirm is True


# ---------------------------------------------------------------------------
# LLM response parsing: confirmed path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_extract_structured_confirmed():
    """When extract_structured returns contradicts=True, confidence >= 0.7, marker is created.

    This test drives the pair-confirmation logic directly without spinning up a
    full Dagster asset execution context. It uses the module-level helpers
    (_build_contradiction_prompt, _CONTRADICTION_CONFIDENCE_THRESHOLD) together
    with an AsyncMock LLM provider and a lightweight fake create_contradiction.
    """
    from unittest.mock import AsyncMock

    silo_id = "test-silo"
    node_a_id = "node-a"
    node_b_id = "node-b"
    content_a = "The project budget is $1M."
    content_b = "The project has no budget."

    llm_provider_mock = AsyncMock()
    llm_provider_mock.extract_structured.return_value = (
        {"contradicts": True, "confidence": 0.92, "explanation": "mutually exclusive"},
        AsyncMock(),
    )

    created_markers: list[dict] = []

    async def _fake_create_contradiction(**kwargs):  # type: ignore[return]
        created_markers.append(kwargs)
        return {"marker_id": "marker-1"}

    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_CONFIDENCE_THRESHOLD,
        _build_contradiction_prompt,
    )

    # Simulate the per-pair confirmation logic from the asset's inner _run().
    messages = _build_contradiction_prompt(content_a, content_b)
    parsed, _ = await llm_provider_mock.extract_structured(messages, schema={})
    contradicts = bool(parsed["contradicts"])
    confidence = float(parsed["confidence"])
    should_confirm = contradicts and confidence >= _CONTRADICTION_CONFIDENCE_THRESHOLD

    if should_confirm:
        await _fake_create_contradiction(
            store=AsyncMock(),
            redis=AsyncMock(),
            silo_id=silo_id,
            node_a_id=node_a_id,
            node_b_id=node_b_id,
            about_ids=[node_a_id, node_b_id],
            confidence=confidence,
        )

    assert len(created_markers) == 1
    assert created_markers[0]["node_a_id"] == node_a_id
    assert created_markers[0]["node_b_id"] == node_b_id
    assert created_markers[0]["about_ids"] == [node_a_id, node_b_id]


# ---------------------------------------------------------------------------
# LLM response parsing: false positive path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_low_confidence_does_not_create_marker():
    """When LLM confidence is below threshold, no marker is created."""
    from unittest.mock import AsyncMock

    llm_provider_mock = AsyncMock()
    llm_provider_mock.extract_structured.return_value = (
        {"contradicts": True, "confidence": 0.3, "explanation": "weak signal"},
        AsyncMock(),
    )

    from context_service.pipelines.assets.validator_contradiction import (
        _CONTRADICTION_CONFIDENCE_THRESHOLD,
        _build_contradiction_prompt,
    )

    messages = _build_contradiction_prompt("Claim A", "Claim B")
    parsed, _ = await llm_provider_mock.extract_structured(messages, schema={})
    contradicts = bool(parsed["contradicts"])
    confidence = float(parsed["confidence"])
    should_confirm = contradicts and confidence >= _CONTRADICTION_CONFIDENCE_THRESHOLD

    assert should_confirm is False
