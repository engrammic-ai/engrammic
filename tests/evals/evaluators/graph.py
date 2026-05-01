from dataclasses import dataclass, field

from pydantic_evals.evaluators import Evaluator, EvaluatorContext


@dataclass(repr=False)
class ChainComplete(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        chain = (ctx.output or {}).get("chain", [])
        root_id = ctx.expected_output.get("root_id", "")
        return bool(chain) and chain[-1] == root_id


@dataclass(repr=False)
class NodeExists(Evaluator):
    def evaluate(self, ctx: EvaluatorContext) -> bool:
        return ctx.output is not None and "id" in ctx.output


@dataclass(repr=False)
class EdgeExists(Evaluator):
    source: str = field(default="")
    target: str = field(default="")

    def evaluate(self, ctx: EvaluatorContext) -> bool:
        edges = (ctx.output or {}).get("edges", [])
        return any(e.get("source") == self.source and e.get("target") == self.target for e in edges)
