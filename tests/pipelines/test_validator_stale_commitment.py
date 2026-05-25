"""Tests for the validator_stale_commitment Dagster asset."""


import pytest

# ---------------------------------------------------------------------------
# Asset surface
# ---------------------------------------------------------------------------


def test_validator_stale_commitment_asset_exists():
    from context_service.pipelines.assets.validator_stale_commitment import (
        validator_stale_commitment_asset,
    )

    assert validator_stale_commitment_asset is not None


def test_validator_stale_commitment_asset_name():
    from context_service.pipelines.assets.validator_stale_commitment import (
        validator_stale_commitment_asset,
    )

    keys = list(validator_stale_commitment_asset.keys)
    assert len(keys) == 1
    assert keys[0].path[-1] == "validator_stale_commitment"


def test_validator_stale_commitment_has_retry_policy():
    from context_service.pipelines.assets.validator_stale_commitment import (
        validator_stale_commitment_asset,
    )

    policy = validator_stale_commitment_asset.op.retry_policy
    assert policy is not None
    assert policy.max_retries == 2


def test_validator_stale_commitment_in_all_assets():
    from context_service.pipelines.assets import all_assets
    from context_service.pipelines.assets.validator_stale_commitment import (
        validator_stale_commitment_asset,
    )

    assert validator_stale_commitment_asset in all_assets


# ---------------------------------------------------------------------------
# Query and key constants
# ---------------------------------------------------------------------------


def test_get_commitments_query_filters_active():
    from context_service.pipelines.assets.validator_stale_commitment import (
        _GET_COMMITMENTS_WITH_NEW_EVIDENCE,
    )

    assert "Commitment" in _GET_COMMITMENTS_WITH_NEW_EVIDENCE
    assert "valid_to IS NULL" in _GET_COMMITMENTS_WITH_NEW_EVIDENCE
    assert "$watermark" in _GET_COMMITMENTS_WITH_NEW_EVIDENCE
    assert "$silo_id" in _GET_COMMITMENTS_WITH_NEW_EVIDENCE


def test_watermark_key_includes_silo_id():
    from context_service.pipelines.assets.validator_stale_commitment import _watermark_key

    key = _watermark_key("silo-abc")
    assert "silo-abc" in key
    assert "stale_commitment" in key


# ---------------------------------------------------------------------------
# LLM prompt builder
# ---------------------------------------------------------------------------


def test_build_stale_prompt_includes_commitment():
    from context_service.pipelines.assets.validator_stale_commitment import _build_stale_prompt

    evidence = [{"id": "e1", "content": "New data contradicts prior assumption."}]
    messages = _build_stale_prompt("The system is stable.", evidence)
    assert any("The system is stable." in m["content"] for m in messages)


def test_build_stale_prompt_includes_evidence():
    from context_service.pipelines.assets.validator_stale_commitment import _build_stale_prompt

    evidence = [{"id": "e1", "content": "System crashed twice this week."}]
    messages = _build_stale_prompt("The system is stable.", evidence)
    assert any("System crashed twice this week." in m["content"] for m in messages)


def test_build_stale_prompt_has_system_and_user():
    from context_service.pipelines.assets.validator_stale_commitment import _build_stale_prompt

    messages = _build_stale_prompt("Commitment text.", [{"id": "e1", "content": "Evidence."}])
    roles = [m["role"] for m in messages]
    assert "system" in roles
    assert "user" in roles


# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------


def test_stale_schema_has_required_fields():
    from context_service.pipelines.assets.validator_stale_commitment import _STALE_SCHEMA

    required = set(_STALE_SCHEMA["required"])
    assert "undermines" in required
    assert "confidence" in required
    assert "explanation" in required


# ---------------------------------------------------------------------------
# Confidence threshold logic
# ---------------------------------------------------------------------------


def test_stale_detected_when_confidence_meets_threshold():
    from context_service.pipelines.assets.validator_stale_commitment import (
        _STALE_CONFIDENCE_THRESHOLD,
    )

    undermines = True
    confidence = 0.8
    should_flag = undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD
    assert should_flag is True


def test_false_positive_when_confidence_below_threshold():
    from context_service.pipelines.assets.validator_stale_commitment import (
        _STALE_CONFIDENCE_THRESHOLD,
    )

    undermines = True
    confidence = 0.5
    should_flag = undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD
    assert should_flag is False


def test_false_positive_when_undermines_false():
    from context_service.pipelines.assets.validator_stale_commitment import (
        _STALE_CONFIDENCE_THRESHOLD,
    )

    undermines = False
    confidence = 0.95
    should_flag = undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD
    assert should_flag is False


# ---------------------------------------------------------------------------
# Watermark defaults
# ---------------------------------------------------------------------------


def test_default_lookback_is_one_hour():
    from context_service.pipelines.assets.validator_stale_commitment import (
        _DEFAULT_LOOKBACK_SECONDS,
    )

    assert _DEFAULT_LOOKBACK_SECONDS == 3600


# ---------------------------------------------------------------------------
# Stale detected path: logic verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_confirmed_logic():
    """LLM returns undermines=true, confidence=0.9 -> stale_detected increments."""
    from context_service.pipelines.assets.validator_stale_commitment import (
        _STALE_CONFIDENCE_THRESHOLD,
        _build_stale_prompt,
    )

    commitment_content = "The API has 99.9% uptime."
    evidence = [{"id": "e1", "content": "The API was down for 6 hours last week."}]

    messages = _build_stale_prompt(commitment_content, evidence)
    assert len(messages) == 2

    # Simulate LLM response
    parsed = {"undermines": True, "confidence": 0.9, "explanation": "Downtime contradicts claim."}
    undermines = bool(parsed["undermines"])
    confidence = float(parsed["confidence"])
    assert undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD


@pytest.mark.asyncio
async def test_not_stale_when_confidence_low():
    """LLM returns undermines=true but confidence=0.4 -> not flagged as stale."""
    from context_service.pipelines.assets.validator_stale_commitment import (
        _STALE_CONFIDENCE_THRESHOLD,
    )

    parsed = {"undermines": True, "confidence": 0.4, "explanation": "Possibly unrelated."}
    undermines = bool(parsed["undermines"])
    confidence = float(parsed["confidence"])
    should_flag = undermines and confidence >= _STALE_CONFIDENCE_THRESHOLD
    assert should_flag is False
