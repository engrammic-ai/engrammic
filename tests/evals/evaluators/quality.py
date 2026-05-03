from dataclasses import dataclass

from pydantic_evals.evaluators import Evaluator, EvaluatorContext


@dataclass(repr=False)
class ClaimStored(Evaluator):
    """Output must contain a non-null claim_id."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return bool((ctx.output or {}).get("claim_id"))


@dataclass(repr=False)
class ClaimRejected(Evaluator):
    """Output must not contain a claim_id (claim was rejected with an error)."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        out = ctx.output or {}
        return out.get("claim_id") is None and bool(out.get("error"))


@dataclass(repr=False)
class EvidenceLinkedCount(Evaluator):
    """Checks that evidence_linked equals the expected count."""

    expected: int = 0

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return (ctx.output or {}).get("evidence_linked") == self.expected


@dataclass(repr=False)
class StepsCountMatches(Evaluator):
    """Checks that stored steps_count equals the expected value."""

    expected: int = 0

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return (ctx.output or {}).get("steps_count") == self.expected


@dataclass(repr=False)
class ConclusionStored(Evaluator):
    """Output conclusion_stored must be True."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return bool((ctx.output or {}).get("conclusion_stored"))


@dataclass(repr=False)
class TargetReachable(Evaluator):
    """target_reachable must be True in link semantics output."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return bool((ctx.output or {}).get("target_reachable"))


@dataclass(repr=False)
class SourceReachableReverse(Evaluator):
    """source_reachable_reverse must be True in link semantics output."""

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return bool((ctx.output or {}).get("source_reachable_reverse"))


@dataclass(repr=False)
class WithinMs(Evaluator):
    """Elapsed wall time (ms) must be below the threshold."""

    threshold_ms: float = 300.0

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        elapsed = (ctx.output or {}).get("elapsed_ms")
        if elapsed is None:
            return False
        return float(elapsed) < self.threshold_ms
