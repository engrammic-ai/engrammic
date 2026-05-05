# tests/pipelines/test_weak_link_review.py
from context_service.pipelines.assets.weak_link_review import (
    DEMOTE_SUPERSEDED_CYPHER,
    PROMOTE_CYPHER,
    PRUNE_CYPHER,
)


def test_promote_cypher_has_required_filters():
    assert "speculative = true" in PROMOTE_CYPHER
    assert "weight >=" in PROMOTE_CYPHER
    assert "edge_heat >=" in PROMOTE_CYPHER


def test_prune_cypher_deletes_weak_links():
    assert "DELETE" in PRUNE_CYPHER
    assert "speculative = true" in PRUNE_CYPHER
    assert "edge_heat <" in PRUNE_CYPHER


def test_demote_handles_superseded():
    assert "superseded = true" in DEMOTE_SUPERSEDED_CYPHER
    assert "speculative = true" in DEMOTE_SUPERSEDED_CYPHER
