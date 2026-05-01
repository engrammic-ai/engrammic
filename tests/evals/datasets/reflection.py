"""Dataset: reflection (MetaObservation) storage and retrieval scenarios."""

from __future__ import annotations

from pydantic_evals import Case, Dataset

from tests.evals.evaluators.graph import NodeExists

reflection_dataset: Dataset[dict, dict, None] = Dataset(
    name="reflection",
    cases=[
        Case(
            name="contradiction_reflection_stored",
            inputs={
                "observation": "I noticed this contradicts earlier observation about weather",
                "observation_type": "contradiction",
                "confidence": 0.75,
                "agent_id": "test-agent",
                "about_content": "The sky is blue",
                "silo_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            },
            expected_output={"id": "placeholder-reflection-id"},
            evaluators=[NodeExists()],
        ),
        Case(
            name="insight_reflection_stored",
            inputs={
                "observation": "This is a well-established fact supported by multiple sources",
                "observation_type": "insight",
                "confidence": 0.9,
                "agent_id": "agent-1",
                "about_content": "Water boils at 100C",
                "silo_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            },
            expected_output={"id": "placeholder-reflection-id"},
            evaluators=[NodeExists()],
        ),
        Case(
            name="confidence_shift_reflection_stored",
            inputs={
                "observation": "Confidence increased after independent verification",
                "observation_type": "confidence_shift",
                "confidence": 0.85,
                "agent_id": "agent-2",
                "about_content": "Water boils at 100C",
                "silo_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            },
            expected_output={"id": "placeholder-reflection-id"},
            evaluators=[NodeExists()],
        ),
    ],
)
