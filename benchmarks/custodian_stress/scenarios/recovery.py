"""Recovery scenarios: crash mid-visit, enum recovery."""

from __future__ import annotations

from typing import Any

from benchmarks.custodian_stress.scenarios.base import (
    ScenarioResult,
    ScenarioTimer,
)


async def test_enum_recovery_uppercase(
    store: Any = None,  # noqa: ARG001
) -> ScenarioResult:
    """Verify model_validator normalizes uppercase enum variants."""
    timer = ScenarioTimer()

    try:
        from context_service.custodian.models import Citation

        with timer:
            # Test uppercase recovery
            citation = Citation.model_validate({"node_id": "test-node", "kind": "PRIMARY"})

        passed = citation.kind == "primary"

        return ScenarioResult(
            name="recovery.test_enum_recovery_uppercase",
            passed=passed,
            duration_s=timer.elapsed_s,
            metrics={},
            error=f"Expected 'primary', got '{citation.kind}'" if not passed else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="recovery.test_enum_recovery_uppercase",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )


async def test_enum_recovery_titlecase(
    store: Any = None,  # noqa: ARG001
) -> ScenarioResult:
    """Verify model_validator normalizes titlecase enum variants."""
    timer = ScenarioTimer()

    try:
        from context_service.custodian.models import FastPassObservation

        with timer:
            obs = FastPassObservation.model_validate(
                {
                    "cluster_character": "dense",
                    "interesting_nodes": [],
                    "suspected_themes": [],
                    "complexity": "High",
                    "needs_deep_pass": True,
                }
            )

        passed = obs.complexity == "high"

        return ScenarioResult(
            name="recovery.test_enum_recovery_titlecase",
            passed=passed,
            duration_s=timer.elapsed_s,
            metrics={},
            error=f"Expected 'high', got '{obs.complexity}'" if not passed else None,
        )

    except Exception as e:
        return ScenarioResult(
            name="recovery.test_enum_recovery_titlecase",
            passed=False,
            duration_s=timer.elapsed_s if timer.end_time else 0,
            error=f"{type(e).__name__}: {e}",
        )
