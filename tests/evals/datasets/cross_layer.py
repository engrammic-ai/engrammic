"""Dataset: cross-layer graph traversal scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.graph import EdgeExists
from tests.evals.evaluators.ranking import TopKContains

cross_layer_dataset: Dataset[dict, dict, None] = Dataset(
    name="cross_layer",
    cases=[
        Case(
            name="claim_references_document",
            inputs={
                "source_id": "claim-aaa",
                "target_id": "doc-bbb",
                "edge_type": "REFERENCES",
                "silo_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            },
            expected_output={"edges": [{"source": "claim-aaa", "target": "doc-bbb"}]},
            evaluators=[EdgeExists(source="claim-aaa", target="doc-bbb")],
        ),
        Case(
            name="fact_promoted_from_claim",
            inputs={
                "source_id": "fact-ccc",
                "target_id": "claim-ddd",
                "edge_type": "PROMOTED_FROM",
                "silo_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            },
            expected_output={"edges": [{"source": "fact-ccc", "target": "claim-ddd"}]},
            evaluators=[EdgeExists(source="fact-ccc", target="claim-ddd")],
        ),
        Case(
            name="graph_depth2_returns_nodes",
            inputs={
                "start_id": "node-eee",
                "depth": 2,
                "silo_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            },
            expected_output={"expected_top": ["node-eee", "node-fff", "node-ggg"]},
            evaluators=[TopKContains(k=3)],
        ),
    ],
)
