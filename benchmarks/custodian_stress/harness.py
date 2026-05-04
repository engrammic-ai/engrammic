"""StressHarness: orchestrates scenario execution and result collection."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from benchmarks.custodian_stress.scenarios.base import ScenarioResult

if TYPE_CHECKING:
    pass


@dataclass
class HarnessConfig:
    """Configuration for stress harness."""

    real_llm: bool = False
    timeout_s: float = 300.0
    parallel_scenarios: bool = False


@dataclass
class HarnessResult:
    """Aggregate result of all scenarios."""

    passed: int = 0
    failed: int = 0
    warned: int = 0
    total_time_s: float = 0.0
    scenarios: list[ScenarioResult] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(
            {
                "passed": self.passed,
                "failed": self.failed,
                "warned": self.warned,
                "total_time_s": round(self.total_time_s, 2),
                "metrics": self.metrics,
                "scenarios": [
                    {
                        "name": s.name,
                        "passed": s.passed,
                        "duration_s": round(s.duration_s, 2),
                        "error": s.error,
                    }
                    for s in self.scenarios
                ],
            },
            indent=2,
        )


class StressHarness:
    """Orchestrates stress testing scenarios."""

    def __init__(
        self,
        store: Any,
        redis: Any | None = None,
        config: HarnessConfig | None = None,
    ) -> None:
        self.store = store
        self.redis = redis
        self.config = config or HarnessConfig()
        self._results: list[ScenarioResult] = []

    def add_result(self, result: ScenarioResult) -> None:
        """Add a scenario result."""
        self._results.append(result)

    def aggregate(self) -> HarnessResult:
        """Aggregate all results into HarnessResult."""
        result = HarnessResult()
        result.scenarios = self._results

        for s in self._results:
            result.total_time_s += s.duration_s
            if s.passed:
                if s.warnings:
                    result.warned += 1
                else:
                    result.passed += 1
            else:
                result.failed += 1

            for key, value in s.metrics.items():
                result.metrics[f"{s.name}.{key}"] = value

        return result

    def print_summary(self) -> None:
        """Print human-readable summary to stdout."""
        for s in self._results:
            status = "PASS" if s.passed else "FAIL"
            if s.passed and s.warnings:
                status = "WARN"

            metrics_str = ""
            if s.metrics:
                metrics_str = " " + " ".join(f"{k}={v:.2f}" for k, v in s.metrics.items())

            error_str = ""
            if s.error:
                error_str = f" {s.error}"

            print(f"{status:4}  {s.name:45} {s.duration_s:6.2f}s{metrics_str}{error_str}")

        agg = self.aggregate()
        print(f"\nTotal: {agg.passed} passed, {agg.failed} failed, {agg.warned} warned in {agg.total_time_s:.2f}s")
