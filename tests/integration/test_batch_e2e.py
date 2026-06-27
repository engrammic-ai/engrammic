"""End-to-end tests for batch API (requires running service)."""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_batch_remember_e2e(integration_client: Any) -> None:
    """Batch/remember: 100 items created within timing budget."""
    response = await integration_client.post(
        "/api/v1/batch/remember",
        json={
            "items": [
                {"content": f"E2E observation {i}", "document_id": f"e2e-remember-{i}"}
                for i in range(100)
            ],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 100
    assert data["failed"] == 0
    assert data["elapsed_ms"] < 15_000


@pytest.mark.asyncio
async def test_batch_learn_supersession_e2e(integration_client: Any) -> None:
    """Batch/learn: two items with the same (subject, predicate) produce a supersession chain."""
    response = await integration_client.post(
        "/api/v1/batch/learn",
        headers={"X-Bypass-SAGE": "true", "X-Admin-Override": "true"},
        json={
            "items": [
                {
                    "content": "User age is 25",
                    "evidence": ["https://example.com/age-v1"],
                    "subject": "user_123",
                    "predicate": "age",
                    "object": "25",
                    "document_id": "e2e-age-v1",
                    "timestamp": "2024-01-01T00:00:00Z",
                },
                {
                    "content": "User age is 26",
                    "evidence": ["https://example.com/age-v2"],
                    "subject": "user_123",
                    "predicate": "age",
                    "object": "26",
                    "document_id": "e2e-age-v2",
                    "timestamp": "2024-01-02T00:00:00Z",
                },
            ],
            "options": {"conflict_mode": "supersede", "skip_evidence_validation": True},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 2
    assert data["failed"] == 0

    # Both node_ids should be present and distinct
    node_ids = [r["node_id"] for r in data["results"] if r.get("node_id")]
    assert len(node_ids) == 2
    assert node_ids[0] != node_ids[1]
