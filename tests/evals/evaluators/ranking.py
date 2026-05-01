from dataclasses import dataclass, field

from pydantic_evals.evaluators import Evaluator, EvaluatorContext


@dataclass(repr=False)
class TopKContains(Evaluator):
    k: int = 3

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        results = ctx.output or []
        top_ids = {r["id"] for r in results[: self.k]}
        expected = ctx.expected_output.get("expected_top", [])
        return all(eid in top_ids for eid in expected)


@dataclass(repr=False)
class RankHigherThan(Evaluator):
    higher: str = field(default="")
    lower: str = field(default="")

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        results = ctx.output or []
        ids = [r["id"] for r in results]
        if self.higher not in ids or self.lower not in ids:
            return False
        return ids.index(self.higher) < ids.index(self.lower)


@dataclass(repr=False)
class AbsentFromTopK(Evaluator):
    k: int = 3

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        results = ctx.output or []
        top_ids = {r["id"] for r in results[: self.k]}
        excluded = ctx.expected_output.get("absent_id", "")
        return excluded not in top_ids
