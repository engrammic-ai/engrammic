"""Smoke tests: custodian output models recover malformed enum variants.

Gemini returns uppercase/titlecase enum variants when the schema requires
lowercase. The model_validator(mode='before') on each output type should
remap them before pydantic validates Literal constraints.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from context_service.custodian.models import (
    Citation,
    FastPassObservation,
    FindingOutput,
    VisitPlan,
)


class TestCitationEnumRecovery:
    def test_uppercase_kind_recovered(self) -> None:
        c = Citation.model_validate({"node_id": "n1", "kind": "PRIMARY"})
        assert c.kind == "primary"

    def test_titlecase_kind_recovered(self) -> None:
        c = Citation.model_validate({"node_id": "n1", "kind": "Supporting"})
        assert c.kind == "supporting"

    def test_correct_kind_passes(self) -> None:
        c = Citation.model_validate({"node_id": "n1", "kind": "primary"})
        assert c.kind == "primary"

    def test_invalid_kind_still_fails(self) -> None:
        with pytest.raises(ValidationError):
            Citation.model_validate({"node_id": "n1", "kind": "tertiary"})


class TestFastPassObservationEnumRecovery:
    def test_uppercase_complexity_recovered(self) -> None:
        obs = FastPassObservation.model_validate(
            {
                "cluster_character": "dense",
                "interesting_nodes": [],
                "suspected_themes": [],
                "complexity": "HIGH",
                "needs_deep_pass": True,
            }
        )
        assert obs.complexity == "high"

    def test_titlecase_complexity_recovered(self) -> None:
        obs = FastPassObservation.model_validate(
            {
                "cluster_character": "sparse",
                "interesting_nodes": [],
                "suspected_themes": [],
                "complexity": "Medium",
                "needs_deep_pass": False,
            }
        )
        assert obs.complexity == "medium"

    def test_invalid_complexity_still_fails(self) -> None:
        with pytest.raises(ValidationError):
            FastPassObservation.model_validate(
                {
                    "cluster_character": "x",
                    "interesting_nodes": [],
                    "suspected_themes": [],
                    "complexity": "extreme",
                    "needs_deep_pass": False,
                }
            )


class TestVisitPlanEnumRecovery:
    def test_uppercase_strategy_recovered(self) -> None:
        plan = VisitPlan.model_validate(
            {
                "strategy": "DEEPEN",
                "tool_call_sequence": [],
                "stop_conditions": [],
            }
        )
        assert plan.strategy == "deepen"

    def test_titlecase_strategy_recovered(self) -> None:
        plan = VisitPlan.model_validate(
            {
                "strategy": "Skip",
                "tool_call_sequence": [],
                "stop_conditions": [],
                "skip_reason": "nothing interesting",
            }
        )
        assert plan.strategy == "skip"

    def test_invalid_strategy_still_fails(self) -> None:
        with pytest.raises(ValidationError):
            VisitPlan.model_validate(
                {
                    "strategy": "explore",
                    "tool_call_sequence": [],
                    "stop_conditions": [],
                }
            )


class TestFindingOutputEnumRecovery:
    def test_uppercase_scope_recovered(self) -> None:
        finding = FindingOutput.model_validate(
            {
                "cluster_id": "c1",
                "silo_id": "s1",
                "scope": "CLUSTER",
                "claims": [],
                "inferred_relations": [],
            }
        )
        assert finding.scope == "cluster"

    def test_titlecase_scope_recovered(self) -> None:
        finding = FindingOutput.model_validate(
            {
                "cluster_id": None,
                "silo_id": "s1",
                "scope": "Silo",
                "claims": [],
                "inferred_relations": [],
            }
        )
        assert finding.scope == "silo"

    def test_invalid_scope_still_fails(self) -> None:
        with pytest.raises(ValidationError):
            FindingOutput.model_validate(
                {
                    "cluster_id": None,
                    "silo_id": "s1",
                    "scope": "global",
                    "claims": [],
                    "inferred_relations": [],
                }
            )
