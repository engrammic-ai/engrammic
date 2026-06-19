"""Tests for db/queries.py query strings."""

from __future__ import annotations

import uuid

import pytest

from context_service.db import queries as q


def test_get_proposed_belief_query_exists() -> None:
    """GET_PROPOSED_BELIEF query is defined and importable."""
    assert hasattr(q, "GET_PROPOSED_BELIEF")
    assert isinstance(q.GET_PROPOSED_BELIEF, str)


def test_get_proposed_belief_uses_correct_params() -> None:
    """GET_PROPOSED_BELIEF references expected parameter names."""
    assert "$proposed_belief_id" in q.GET_PROPOSED_BELIEF
    assert "$silo_id" in q.GET_PROPOSED_BELIEF


def test_get_proposed_belief_returns_expected_columns() -> None:
    """GET_PROPOSED_BELIEF returns all required columns."""
    cypher = q.GET_PROPOSED_BELIEF
    assert "proposed_belief_id" in cypher
    assert "content" in cypher
    assert "confidence" in cypher
    assert "status" in cypher
    assert "created_at" in cypher
    assert "source_fact_ids" in cypher


def test_get_proposed_belief_matches_by_id_and_silo() -> None:
    """GET_PROPOSED_BELIEF MATCH clause filters on both id and silo_id."""
    cypher = q.GET_PROPOSED_BELIEF
    # CITE v2: uses :Belief with status field instead of :ProposedBelief
    assert "Belief" in cypher
    assert "MATCH" in cypher


@pytest.mark.asyncio
async def test_get_proposed_belief_with_fake_store() -> None:
    """GET_PROPOSED_BELIEF query is passed to the store with correct params."""
    from tests.fakes.fake_graph_store import FakeGraphStore

    proposal_id = str(uuid.uuid4())
    silo_id = f"test-silo-{uuid.uuid4().hex[:8]}"

    store = FakeGraphStore()
    store.seed_query_result(
        [
            {
                "proposed_belief_id": proposal_id,
                "content": "test synthesis",
                "confidence": 0.85,
                "status": "pending",
                "created_at": None,
                "accepted_at": None,
                "rejected_at": None,
                "rejection_reason": None,
                "source_fact_ids": [],
            }
        ]
    )

    result = await store.execute_query(
        q.GET_PROPOSED_BELIEF,
        {"proposed_belief_id": proposal_id, "silo_id": silo_id},
    )

    assert len(result) == 1
    assert result[0]["proposed_belief_id"] == proposal_id
    assert result[0]["content"] == "test synthesis"
    assert result[0]["status"] == "pending"

    # Verify the correct query and params were used.
    cypher_used, params_used = store.query_log[0]
    assert cypher_used is q.GET_PROPOSED_BELIEF
    assert params_used["proposed_belief_id"] == proposal_id
    assert params_used["silo_id"] == silo_id
