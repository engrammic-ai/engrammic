"""Dataset: provenance chain integrity scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.graph import ChainComplete, NodeExists

provenance_dataset: Dataset[dict, dict, None] = Dataset(
    name="provenance",
    cases=[
        Case(
            name="claim_chain_reaches_document",
            inputs={
                "start_node_type": "Claim",
                "start_content": "Alice is a property owner",
                "root_content": "Alice owns a property in Berlin.",
                "edge_chain": [("Claim", "REFERENCES", "Document")],
                "silo_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
            expected_output={"root_id": "placeholder-doc-id"},
            evaluators=[ChainComplete()],
        ),
        Case(
            name="fact_chain_reaches_document_multi_hop",
            inputs={
                "start_node_type": "Fact",
                "start_content": "Promoted fact about Berlin",
                "root_content": "Source document about Berlin",
                "edge_chain": [
                    ("Fact", "PROMOTED_FROM", "Claim"),
                    ("Claim", "REFERENCES", "Document"),
                ],
                "silo_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
            expected_output={"root_id": "placeholder-doc-id"},
            evaluators=[ChainComplete()],
        ),
        Case(
            name="isolated_node_has_empty_chain",
            inputs={
                "start_node_type": "Claim",
                "start_content": "Orphan claim with no provenance",
                "edge_chain": [],
                "silo_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            },
            expected_output={"id": "placeholder-claim-id"},
            evaluators=[NodeExists()],
        ),
    ],
)
