"""Dataset: claim promotion (Claim -> Fact) quality scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.graph import NodeExists


def _promoted_output(claim_id: str, fact_id: str) -> dict:
    return {
        "id": fact_id,
        "edges": [{"source": fact_id, "target": claim_id, "type": "PROMOTED_FROM"}],
    }


claim_promotion_dataset: Dataset[dict, dict | None, None] = Dataset(
    name="claim_promotion",
    cases=[
        Case(
            name="authoritative_high_confidence_promotes",
            inputs={
                "claim": "The capital of France is Paris",
                "confidence": 0.85,
                "source_tier": "authoritative",
                "evidence": ["node:ref-1"],
            },
            expected_output={
                "id": "placeholder-fact-id",
                "edges": [
                    {
                        "source": "placeholder-fact-id",
                        "target": "placeholder-claim-id",
                        "type": "PROMOTED_FROM",
                    }
                ],
            },
            evaluators=[NodeExists()],
        ),
        Case(
            name="low_confidence_not_promoted",
            inputs={
                "claim": "The sky is green",
                "confidence": 0.5,
                "source_tier": "authoritative",
                "evidence": ["node:ref-2"],
            },
            expected_output=None,
            evaluators=[],
        ),
        Case(
            name="derived_from_edges_counted",
            inputs={
                "claim": "Berlin is in Germany",
                "confidence": 0.85,
                "source_tier": "authoritative",
                "evidence": [],
                "auto_count": True,
            },
            expected_output={
                "id": "placeholder-fact-id",
                "edges": [],
            },
            evaluators=[NodeExists()],
        ),
    ],
)
