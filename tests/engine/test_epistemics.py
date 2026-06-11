"""Tests for canonical confidence interpretation (epistemic hygiene pre-fix)."""

from __future__ import annotations

from context_service.engine.epistemics import effective_confidence, read_confidence


class TestReadConfidence:
    def test_missing_key_is_none(self) -> None:
        assert read_confidence({}) is None

    def test_none_value_is_none(self) -> None:
        assert read_confidence({"confidence": None}) is None

    def test_zero_is_zero_not_default(self) -> None:
        # The falsy bug this module exists to kill:
        # `props.get("confidence") or 1.0` maps 0.0 -> 1.0.
        assert read_confidence({"confidence": 0.0}) == 0.0

    def test_present_value_passes_through(self) -> None:
        assert read_confidence({"confidence": 0.42}) == 0.42

    def test_clamped_above(self) -> None:
        assert read_confidence({"confidence": 1.7}) == 1.0

    def test_clamped_below(self) -> None:
        assert read_confidence({"confidence": -0.3}) == 0.0

    def test_string_number_coerced(self) -> None:
        # Graph rows sometimes deserialize numerics as strings.
        assert read_confidence({"confidence": "0.5"}) == 0.5


class TestEffectiveConfidence:
    def test_missing_uses_when_missing_default(self) -> None:
        assert effective_confidence({}) == 1.0

    def test_none_value_uses_when_missing_default(self) -> None:
        assert effective_confidence({"confidence": None}) == 1.0

    def test_zero_respected(self) -> None:
        assert effective_confidence({"confidence": 0.0}) == 0.0

    def test_custom_when_missing(self) -> None:
        assert effective_confidence({}, when_missing=0.5) == 0.5

    def test_present_value_ignores_when_missing(self) -> None:
        assert effective_confidence({"confidence": 0.3}, when_missing=0.9) == 0.3


class TestQueryPathRegression:
    """The falsy bug as it manifested: services/context.py query() promoted
    stored 0.0 confidence to 1.0 via `or 1.0`. These pin the helper's
    behavior at the exact values that path consumes."""

    def test_assessed_zero_stays_zero(self) -> None:
        props = {"layer": "knowledge", "confidence": 0.0}
        assert effective_confidence(props) == 0.0

    def test_unassessed_is_full_trust(self) -> None:
        props = {"layer": "knowledge"}
        assert effective_confidence(props) == 1.0
