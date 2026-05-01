"""Dataset: silo isolation boundary scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.ranking import AbsentFromTopK

silo_isolation_dataset: Dataset[dict, list[dict], None] = Dataset(
    name="silo_isolation",
    cases=[
        Case(
            name="query_results_scoped_to_silo",
            inputs={
                "query": "knowledge graph embeddings",
                "querying_silo": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "other_silo": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "doc_in_other_silo": "other-silo-doc-001",
            },
            expected_output={"absent_id": "other-silo-doc-001"},
            evaluators=[AbsentFromTopK(k=10)],
        ),
        Case(
            name="reflections_scoped_to_silo",
            inputs={
                "node_id": "shared-node-id-001",
                "querying_silo": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "other_silo": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "reflection_in_other_silo": "reflection-in-other-silo-001",
            },
            expected_output={"absent_id": "reflection-in-other-silo-001"},
            evaluators=[AbsentFromTopK(k=10)],
        ),
        Case(
            name="writes_do_not_cross_silos",
            inputs={
                "content": "Sensitive data that must stay in silo A",
                "writing_silo": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "checking_silo": "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "written_node_id": "silo-a-exclusive-node",
            },
            expected_output={"absent_id": "silo-a-exclusive-node"},
            evaluators=[AbsentFromTopK(k=10)],
        ),
    ],
)
